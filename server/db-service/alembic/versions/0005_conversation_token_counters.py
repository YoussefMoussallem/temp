"""Add per-conversation accumulated token counters.

Two columns capture the running totals so ``/context`` can show the actual
input footprint of a conversation rather than approximating from message
content. ``/clear`` resets them alongside truncating messages.

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-28
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE conversations ADD COLUMN total_input_tokens BIGINT NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE conversations ADD COLUMN total_output_tokens BIGINT NOT NULL DEFAULT 0")


def downgrade() -> None:
    op.execute("ALTER TABLE conversations DROP COLUMN IF EXISTS total_output_tokens")
    op.execute("ALTER TABLE conversations DROP COLUMN IF EXISTS total_input_tokens")
