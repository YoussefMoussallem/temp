"""Parameterised SQL for the master_layouts table.

Two upsert behaviours encoded in the INSERT:

1. ``ON CONFLICT (master_id, master_index, layout_index) DO UPDATE``
   refreshes only the *extractor-controlled* fields. User edits to
   ``user_kind``, ``enabled``, ``is_default``, ``position``, and
   ``notes`` survive a re-extraction (e.g. when the user re-uploads
   the same template after we improved the classifier).

2. ``preview_blob_url`` uses ``COALESCE`` so a re-upsert without a
   fresh URL preserves the old one — but a re-upsert *with* a new
   URL replaces (re-rendering on every upload would otherwise leave
   stale URLs after a render path improvement).
"""

_COLUMNS = (
    "id, master_id, master_index, layout_index, name, "
    "auto_kind, user_kind, enabled, is_default, position, notes, "
    "preview_blob_url, placeholders, safe_area, theme_index, "
    "font_major, font_minor, palette, created_at, updated_at"
)

UPSERT = f"""
    INSERT INTO master_layouts (
        master_id, master_index, layout_index, name, auto_kind,
        position, placeholders, safe_area, theme_index,
        font_major, font_minor, palette, preview_blob_url
    )
    VALUES (
        $1, $2, $3, $4, $5,
        $6, $7::jsonb, $8::jsonb, $9,
        $10, $11, $12::jsonb, $13
    )
    ON CONFLICT (master_id, master_index, layout_index) DO UPDATE SET
        name              = EXCLUDED.name,
        auto_kind         = EXCLUDED.auto_kind,
        placeholders      = EXCLUDED.placeholders,
        safe_area         = EXCLUDED.safe_area,
        theme_index       = EXCLUDED.theme_index,
        font_major        = EXCLUDED.font_major,
        font_minor        = EXCLUDED.font_minor,
        palette           = EXCLUDED.palette,
        preview_blob_url  = COALESCE(EXCLUDED.preview_blob_url, master_layouts.preview_blob_url),
        updated_at        = now()
    RETURNING {_COLUMNS}
"""

GET = f"""
    SELECT {_COLUMNS}
    FROM master_layouts
    WHERE id = $1
"""

LIST_BY_MASTER = f"""
    SELECT {_COLUMNS}
    FROM master_layouts
    WHERE master_id = $1
    ORDER BY position, master_index, layout_index
"""

# Patch endpoint helper — only the listed columns may be updated by
# the user-controlled curation UI. NULL values mean "leave unchanged"
# via COALESCE; the empty-string sentinel for notes is intentional
# (user can clear notes by sending an empty string).
UPDATE = f"""
    UPDATE master_layouts
    SET user_kind   = CASE WHEN $2::text = '' THEN NULL
                           WHEN $2 IS NULL THEN user_kind
                           ELSE $2 END,
        enabled     = COALESCE($3, enabled),
        position    = COALESCE($4, position),
        notes       = CASE WHEN $5::text = '__CLEAR__' THEN NULL
                           WHEN $5 IS NULL THEN notes
                           ELSE $5 END,
        is_default  = COALESCE($6, is_default),
        updated_at  = now()
    WHERE id = $1
    RETURNING {_COLUMNS}
"""

# Two-step transaction body for "set layout L as default for its
# kind". Step 1 clears any other layout on the same master that is
# currently default for the same kind. Step 2 sets the target.
CLEAR_DEFAULT_FOR_KIND = """
    UPDATE master_layouts
    SET is_default = FALSE, updated_at = now()
    WHERE master_id = $1
      AND COALESCE(user_kind, auto_kind) = $2
      AND is_default = TRUE
"""

SET_DEFAULT = """
    UPDATE master_layouts
    SET is_default = TRUE, updated_at = now()
    WHERE id = $1
"""
