"""Add ``memory_model`` admin setting.

Memory structuring (UI-driven create / edit of long-term memories
via plain-text input) calls an LLM to convert the user's note into
the persisted schema. Up to now it used ``default_model`` so the
admin had no way to point memory at a cheaper / faster model.

Adds the row in the same shape as the other model settings — empty
string seed value, resolved with fallback to ``default_model`` at
read time (see app_settings_client.resolve).

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-11
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "INSERT INTO app_settings (key, value) "
        "VALUES ('memory_model', '\"\"'::jsonb) "
        "ON CONFLICT (key) DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DELETE FROM app_settings WHERE key = 'memory_model'")
