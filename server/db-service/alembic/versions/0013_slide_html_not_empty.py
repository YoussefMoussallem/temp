"""Reject empty / whitespace-only slide HTML at the DB level.

The agent tool already validates a minimum HTML length, but a DB-level
``CHECK`` constraint is a second guardrail in case the tool path is
ever bypassed (direct ``/api/projects/{id}/slides`` POST, a future
import job, a misbehaving migration, etc.). Empty-payload slides
have surfaced in the wild — silently inserting blanks is worse than
surfacing a clean 400 the caller can react to.

The threshold here (40 chars) is intentionally looser than the agent
tool's ``_MIN_HTML_CHARS`` floor (200): the tool rejects "didn't
finish a slide" payloads, the DB rejects "this is definitely not a
slide" payloads. Both layers can tighten independently.

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-12
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Check if constraint already exists (may have been created by old migration)
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint 
                WHERE conname = 'slides_html_not_empty'
            ) THEN
                ALTER TABLE slides 
                ADD CONSTRAINT slides_html_not_empty 
                CHECK (length(btrim(html)) >= 40);
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE slides DROP CONSTRAINT IF EXISTS slides_html_not_empty")
