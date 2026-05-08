"""Add per-conversation accumulated cost in USD.

Mirrors the token counters added in 0005 — same precision as the
existing ``usage_records.cost_usd`` column (NUMERIC(12, 8)) so cost
sums across both tables can be reasoned about in the same units.

Each turn the agent computes cost via ``calculate_cost(model, in, out)``
in ``litellm_bridge`` and bumps this column atomically alongside the
token deltas. ``/clear`` zeroes it.

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-29
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE conversations "
        "ADD COLUMN total_cost_usd NUMERIC(12, 8) NOT NULL DEFAULT 0"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE conversations DROP COLUMN IF EXISTS total_cost_usd")
