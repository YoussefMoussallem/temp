"""Parameterised SQL for the masters table.

All five columns live in the default projection — ``manifest`` is small
(typically 2-5 KB JSONB), and the BYTEA-bytes-in-Postgres concern from
v2-old no longer applies because we go straight to blob.

The INSERT clause does an idempotent-by-SHA upsert: re-importing the
same .pptx into the same project refreshes name + manifest +
blob_url and keeps the original id. Callers can write the same row
twice and never get a duplicate.
"""

_COLUMNS = (
    "id, project_id, name, source_sha256, manifest, "
    "source_pptx_blob_url, fonts_assets, created_at, updated_at"
)

INSERT = f"""
    INSERT INTO masters (
        project_id, name, source_sha256, manifest, source_pptx_blob_url,
        fonts_assets
    )
    VALUES ($1, $2, $3, $4::jsonb, $5, $6::jsonb)
    ON CONFLICT (project_id, source_sha256) WHERE source_sha256 IS NOT NULL
    DO UPDATE SET
        name                 = EXCLUDED.name,
        manifest             = EXCLUDED.manifest,
        source_pptx_blob_url = COALESCE(EXCLUDED.source_pptx_blob_url, masters.source_pptx_blob_url),
        fonts_assets         = EXCLUDED.fonts_assets,
        updated_at           = now()
    RETURNING {_COLUMNS}
"""

GET = f"""
    SELECT {_COLUMNS}
    FROM masters
    WHERE id = $1
"""

LIST_BY_PROJECT = f"""
    SELECT {_COLUMNS}
    FROM masters
    WHERE project_id = $1
    ORDER BY created_at DESC
"""

DELETE = "DELETE FROM masters WHERE id = $1"

# Active-master pointer lives on the projects table; touching it via
# the masters repo keeps the surface cohesive (callers don't import
# the projects repo just to flip a pointer).
SET_ACTIVE = """
    UPDATE projects
    SET active_master_id = $2,
        updated_at = now()
    WHERE id = $1
"""

# Read the project's active_master_id. Returns NULL when no master is
# pinned. Surfaced alongside the masters list so the FE can render the
# "active" pill on the right card without a second round-trip.
GET_ACTIVE_FOR_PROJECT = """
    SELECT active_master_id
    FROM projects
    WHERE id = $1
"""
