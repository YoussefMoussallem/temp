"""Add ``masters`` table, ``projects.active_master_id``, and the
``slides`` columns the new generation path needs.

A *master* is the inheritance contract for a project's slides — the
canvas size, theme tokens (fonts + palette), safe area, locked chrome,
and the layout menu — extracted once from an uploaded .pptx. The
extracted manifest persists as JSONB; the original .pptx bytes go to
Azure Blob (URL stored here, never raw bytes in Postgres).

This migration is intentionally *additive*. Existing rows untouched:

* New columns on ``projects`` and ``slides`` are nullable and default
  NULL, so legacy rows keep working.
* No data migration; nothing to backfill.

The repository layer in the next commit assumes this schema.

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-11
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE masters (
            id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id            UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            name                  VARCHAR(256) NOT NULL,
            source_sha256         VARCHAR(64),
            manifest              JSONB NOT NULL,
            source_pptx_blob_url  TEXT,
            created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX ix_masters_project_created ON masters (project_id, created_at DESC)")
    # Re-uploading the same .pptx into the same project is idempotent —
    # the upsert clause in the repository keys on this index.
    op.execute(
        "CREATE UNIQUE INDEX uq_masters_project_sha "
        "ON masters (project_id, source_sha256) "
        "WHERE source_sha256 IS NOT NULL"
    )

    # Explicit active master per project. Nullable: a project can exist
    # without a master, in which case the legacy CreateSlide flow runs.
    # ON DELETE SET NULL so deleting a master doesn't cascade-orphan
    # the project.
    op.execute(
        "ALTER TABLE projects ADD COLUMN active_master_id "
        "UUID REFERENCES masters(id) ON DELETE SET NULL"
    )

    # Slides gain master + scene linkage. Nullable for legacy slides
    # authored via CreateSlide (HTML-only). New slides via GenerateSlide
    # set both.
    op.execute(
        "ALTER TABLE slides ADD COLUMN master_id UUID REFERENCES masters(id) ON DELETE SET NULL"
    )
    op.execute("ALTER TABLE slides ADD COLUMN scene_graph JSONB")
    op.execute("CREATE INDEX ix_slides_master ON slides (master_id) WHERE master_id IS NOT NULL")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_slides_master")
    op.execute("ALTER TABLE slides DROP COLUMN IF EXISTS scene_graph")
    op.execute("ALTER TABLE slides DROP COLUMN IF EXISTS master_id")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS active_master_id")
    op.execute("DROP INDEX IF EXISTS uq_masters_project_sha")
    op.execute("DROP INDEX IF EXISTS ix_masters_project_created")
    op.execute("DROP TABLE IF EXISTS masters")
