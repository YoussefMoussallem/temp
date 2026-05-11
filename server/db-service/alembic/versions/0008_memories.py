"""Add ``user_memories`` and ``project_memories`` — long-term agent memory.

Two scopes, kept as separate tables because they encode different
lifecycles and access models:

* ``user_memories`` — facts about the user (role, preferences, feedback
  patterns). Loads across every conversation the user has. Row-locked
  to ``user_id``; never shared.
* ``project_memories`` — facts about the project (audience, deadline,
  decisions, references). Loads only inside that project's
  conversations. Inherits the project's existing access model;
  ``created_by_user_id`` is audit only, not access control.

Both rows carry frontmatter-style fields (``slug``, ``type``, ``name``,
``description``) plus a freeform ``body``. The ``slug`` is the
addressable handle (mirrors RevitCode's memdir file naming): unique
within scope, kebab/snake case, ≤64 chars. The ``description`` field
gets the 150-char cap baked in via VARCHAR so the per-turn prompt
index stays bounded without a runtime check.

Phase 1 ships headless — no UI page, no auto-extract. Memory is
exposed to the model through four tools (SaveMemory, ReadMemory,
ListUserMemories, ListProjectMemories); the model decides when each
is relevant.

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-08
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # user_memories — scope: one user, follows them across all conversations
    op.execute("""
        CREATE TABLE user_memories (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id     VARCHAR(128) NOT NULL REFERENCES users(azure_oid) ON DELETE CASCADE,
            slug        VARCHAR(64) NOT NULL,
            type        VARCHAR(32) NOT NULL,
            name        VARCHAR(120) NOT NULL,
            description VARCHAR(150) NOT NULL,
            body        TEXT NOT NULL,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (user_id, slug)
        )
    """)
    op.execute("CREATE INDEX ix_user_memories_user ON user_memories (user_id)")

    # project_memories — scope: one project, inherits the project's access model
    op.execute("""
        CREATE TABLE project_memories (
            id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id         UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            slug               VARCHAR(64) NOT NULL,
            type               VARCHAR(32) NOT NULL,
            name               VARCHAR(120) NOT NULL,
            description        VARCHAR(150) NOT NULL,
            body               TEXT NOT NULL,
            created_by_user_id VARCHAR(128) NOT NULL REFERENCES users(azure_oid),
            created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (project_id, slug)
        )
    """)
    op.execute("CREATE INDEX ix_project_memories_project ON project_memories (project_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS project_memories")
    op.execute("DROP TABLE IF EXISTS user_memories")
