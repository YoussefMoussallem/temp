"""Project members — maps users to projects with a role.

Revision ID: 0004
Revises: 0001
Create Date: 2026-04-28

Note on the revision chain
--------------------------
Originally targeted 0003, but 0001/0002/0003 were consolidated into a
single ``0001_initial_schema.py`` migration. ``down_revision`` was
re-pointed at ``0001`` so ``alembic upgrade head`` resolves cleanly on
both fresh clones and existing dev DBs (where alembic_version was
manually stamped to '0004' after the consolidation).
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE project_members (
            user_id    VARCHAR(128) NOT NULL REFERENCES users(azure_oid) ON DELETE CASCADE,
            project_id UUID         NOT NULL REFERENCES projects(id)    ON DELETE CASCADE,
            role       VARCHAR(32)  NOT NULL DEFAULT 'viewer'
                       CHECK (role IN ('owner', 'editor', 'viewer')),
            joined_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, project_id)
        )
    """)
    op.execute("CREATE INDEX ix_project_members_project ON project_members (project_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS project_members")
