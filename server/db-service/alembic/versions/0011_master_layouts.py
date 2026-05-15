"""Add ``master_layouts`` table.

Phase 2.3a. The masters table from migration 0010 stores one row per
imported PowerPoint template (manifest JSONB + blob URL for the bytes).
Phase 2.1 made the extractor walk every master and every layout, but
the layouts still live inside ``masters.manifest`` JSONB — fine for
read, awkward for the per-layout PATCH endpoints (toggle enabled,
override kind, mark default-for-kind, edit notes, reorder) the
curation UI needs.

This migration normalises layouts into their own table so per-layout
mutations are clean SQL UPDATEs instead of read-modify-write of a
deeply-nested JSONB blob.

Re-extraction safety
--------------------
``UNIQUE (master_id, master_index, layout_index)`` lets us UPSERT one
row per (master, layout) pair on every import. Re-importing the same
template refreshes the *extractor-controlled* fields (name, auto_kind,
placeholders, safe_area, palette, fonts) but does NOT clobber the
*user-controlled* ones (user_kind, enabled, is_default, position,
notes). The repository handles that selectively.

One-default-per-kind
--------------------
``UNIQUE (master_id, user_kind) WHERE is_default = TRUE`` guarantees a
master has at most one preferred layout for each kind. Setting a new
default on layout B (kind=cover) must clear is_default on layout A
(also kind=cover) of the same master — the router does this in a
single transaction so the unique constraint never fires.

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-12
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE master_layouts (
            id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            master_id          UUID NOT NULL REFERENCES masters(id) ON DELETE CASCADE,
            master_index       INT NOT NULL,
            layout_index       INT NOT NULL,
            name               TEXT NOT NULL DEFAULT '',
            auto_kind          TEXT NOT NULL DEFAULT 'other',
            user_kind          TEXT,
            enabled            BOOLEAN NOT NULL DEFAULT TRUE,
            is_default         BOOLEAN NOT NULL DEFAULT FALSE,
            position           INT NOT NULL DEFAULT 0,
            notes              TEXT,
            preview_blob_url   TEXT,
            placeholders       JSONB NOT NULL DEFAULT '[]'::jsonb,
            safe_area          JSONB,
            theme_index        INT NOT NULL DEFAULT 1,
            font_major         TEXT,
            font_minor         TEXT,
            palette            JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )

    op.execute(
        "CREATE INDEX ix_master_layouts_master_position ON master_layouts (master_id, position)"
    )
    op.execute(
        "CREATE INDEX ix_master_layouts_enabled ON master_layouts (master_id) WHERE enabled = TRUE"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_master_layouts_position "
        "ON master_layouts (master_id, master_index, layout_index)"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_master_layouts_default "
        "ON master_layouts (master_id, user_kind) "
        "WHERE is_default = TRUE"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_master_layouts_default")
    op.execute("DROP INDEX IF EXISTS uq_master_layouts_position")
    op.execute("DROP INDEX IF EXISTS ix_master_layouts_enabled")
    op.execute("DROP INDEX IF EXISTS ix_master_layouts_master_position")
    op.execute("DROP TABLE IF EXISTS master_layouts")
