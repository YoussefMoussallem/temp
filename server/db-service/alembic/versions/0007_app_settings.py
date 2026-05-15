"""Add ``app_settings`` — tenant-wide admin-managed key/value config.

Industry-standard "system settings" pattern: a single key/value table
keyed by ``key TEXT`` with a ``value JSONB`` payload. Chose key/value
over a single-row table with one column per setting because:

* Adding a new admin-tunable knob is a row insert, not an ALTER TABLE.
* Heterogeneous value shapes (strings now; ints / objects later)
  are first-class via JSONB.
* Audit fields (``updated_at`` / ``updated_by``) live in one place
  instead of being repeated on every column.

Three rows are seeded for the model defaults that used to be
configured per-user in the chat UI / SettingsModal (main-loop / search
/ export model). Empty string values are valid — the runtime treats a
blank ``search_model`` as "fall back to the main-loop model", matching
the historical ``SEARCH_LLM_MODEL=""`` behaviour.

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-07
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Seed rows. Empty values are intentional — admins set them via the
# admin panel. The backend's resolution layer falls back to env
# (``DEFAULT_LLM_MODEL`` / ``SEARCH_LLM_MODEL``) when a row is blank
# so a fresh deploy with no admin action keeps working.
_SEED_KEYS = ("default_model", "search_model", "export_model")


def upgrade() -> None:
    op.execute("""
        CREATE TABLE app_settings (
            key        VARCHAR(64) PRIMARY KEY,
            value      JSONB NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_by VARCHAR(128)
        )
    """)
    for key in _SEED_KEYS:
        op.execute(
            f"INSERT INTO app_settings (key, value) VALUES ('{key}', '\"\"'::jsonb) "
            "ON CONFLICT (key) DO NOTHING"
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS app_settings")
