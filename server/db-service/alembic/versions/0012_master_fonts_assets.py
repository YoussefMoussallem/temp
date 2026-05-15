"""Add ``masters.fonts_assets`` for bundled brand fonts.

A *template* in this codebase = master + theme + bundled fonts. The
master row already carries master + theme (geometry + palette + font
*names* in ``manifest``). This migration adds the third leg: the actual
displayable font bytes a user uploads alongside the .pptx.

Fonts live in Azure Blob (same container as the source pptx, under a
``fonts/`` prefix). This column stores the metadata: family, weight,
style, source (uploaded vs OOXML-embedded), filename, and the resolved
blob URL.

Shape of each entry::

    {
      "filename": "STCForward-Bold.ttf",
      "family":   "STC Forward",
      "weight":   700,
      "style":    "normal",
      "source":   "uploaded",
      "blob_url": "https://.../fonts/STCForward-Bold.ttf"
    }

Default ``[]`` so existing rows behave as if no fonts were uploaded.
The consumption side (iframe ``@font-face`` injection) is intentionally
deferred — this migration only persists what users hand us.

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-12
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE masters ADD COLUMN fonts_assets JSONB NOT NULL DEFAULT '[]'::jsonb")


def downgrade() -> None:
    op.execute("ALTER TABLE masters DROP COLUMN IF EXISTS fonts_assets")
