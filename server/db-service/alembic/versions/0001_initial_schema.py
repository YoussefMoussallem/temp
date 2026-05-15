"""Initial schema — users, usage_records, projects, conversations, messages, slides.

Revision ID: 0001
Revises: None
Create Date: 2026-04-17
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE users (
            azure_oid    VARCHAR(128) PRIMARY KEY,
            email        VARCHAR(256) NOT NULL UNIQUE,
            display_name VARCHAR(256),
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_users_email ON users (email)")

    op.execute("""
        CREATE TABLE usage_records (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id       VARCHAR(128) NOT NULL REFERENCES users(azure_oid),
            model         VARCHAR(128) NOT NULL,
            input_tokens  INTEGER NOT NULL,
            output_tokens INTEGER NOT NULL,
            cost_usd      NUMERIC(12,8) NOT NULL,
            recorded_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_usage_user_recorded ON usage_records (user_id, recorded_at)")
    op.execute("CREATE INDEX ix_usage_model ON usage_records (model)")
    op.execute("CREATE INDEX ix_usage_recorded_at ON usage_records (recorded_at)")

    op.execute("""
        CREATE TABLE projects (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id     VARCHAR(128) NOT NULL REFERENCES users(azure_oid) ON DELETE CASCADE,
            name        VARCHAR(256) NOT NULL,
            description TEXT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_projects_user_updated ON projects (user_id, updated_at DESC)")

    op.execute("""
        CREATE TABLE conversations (
            id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id     UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            title          VARCHAR(256) NOT NULL DEFAULT 'Untitled',
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_active_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            message_count  INTEGER NOT NULL DEFAULT 0
        )
    """)
    op.execute(
        "CREATE INDEX ix_conversations_project_active "
        "ON conversations (project_id, last_active_at DESC)"
    )

    op.execute("""
        CREATE TABLE messages (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            sequence        INTEGER NOT NULL,
            role            VARCHAR(16) NOT NULL
                            CHECK (role IN ('user', 'assistant', 'system')),
            content         JSONB NOT NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (conversation_id, sequence)
        )
    """)
    op.execute("CREATE INDEX ix_messages_conv_sequence ON messages (conversation_id, sequence)")

    op.execute("""
        CREATE TABLE slides (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id  UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            position    INTEGER NOT NULL,
            title       VARCHAR(256),
            html        TEXT NOT NULL,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_slides_project_position ON slides (project_id, position)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS slides")
    op.execute("DROP TABLE IF EXISTS messages")
    op.execute("DROP TABLE IF EXISTS conversations")
    op.execute("DROP TABLE IF EXISTS projects")
    op.execute("DROP TABLE IF EXISTS usage_records")
    op.execute("DROP TABLE IF EXISTS users")
