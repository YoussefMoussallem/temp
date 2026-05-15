"""Enforce unique (project_id, position) on slides, deferrable.

After-shape decision for parallel CreateSlide: the model emits multiple
creates with pre-numbered ``position`` values and the loop runs them
concurrently. Without a unique constraint, two creates that happen to
pick the same position both succeed and the deck has duplicates at
that slot. A normal unique constraint can't be used because the
existing ``reorder_slide`` / ``create_slide(after_slide_id)`` /
``delete_slide`` paths produce *transient* duplicates inside their
transactions while shifting positions around — those would fail
at the first interim UPDATE.

A DEFERRABLE INITIALLY IMMEDIATE constraint is exactly the right tool:

  * Immediate by default → two parallel INSERTs at the same position
    in autonomous transactions collide at INSERT time. One wins, the
    other surfaces a UniqueViolationError that the repo turns into a
    clean 400 the agent can retry against.
  * Deferrable → the shift/renumber paths call
    ``SET CONSTRAINTS slides_project_position_unique DEFERRED`` inside
    their transactions so the check moves to COMMIT, and the
    intermediate duplicates from sequential SET_POSITION updates are
    tolerated.

Revision ID: 0014
Revises: 0013
Create Date: 2026-05-12
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0014"
down_revision: Union[str, None] = "0013"
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
                WHERE conname = 'slides_project_position_unique'
            ) THEN
                ALTER TABLE slides 
                ADD CONSTRAINT slides_project_position_unique 
                UNIQUE (project_id, position) 
                DEFERRABLE INITIALLY IMMEDIATE;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE slides DROP CONSTRAINT IF EXISTS slides_project_position_unique")
