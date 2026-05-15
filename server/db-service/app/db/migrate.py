"""Forward-only SQL migration runner.

Migrations live as numbered ``.sql`` files::

    0001_create_sessions.sql
    0002_create_usage.sql

Each file is executed inside a transaction.  A ``_migrations`` ledger table
tracks which files have already been applied.
"""

from __future__ import annotations

import logging
from pathlib import Path

import asyncpg

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

LEDGER_DDL = """\
CREATE TABLE IF NOT EXISTS _migrations (
    id          SERIAL PRIMARY KEY,
    filename    TEXT NOT NULL UNIQUE,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


async def run_migrations(conn: asyncpg.Connection, *, directory: Path | None = None) -> int:
    """Apply pending ``.sql`` files and return the number applied.

    Parameters
    ----------
    conn:
        A single connection (not a pool) so migrations run in sequence.
    directory:
        Override the default ``migrations/`` folder.
    """
    migrations_dir = directory or MIGRATIONS_DIR

    await conn.execute(LEDGER_DDL)

    applied: set[str] = {
        row["filename"] for row in await conn.fetch("SELECT filename FROM _migrations")
    }

    sql_files = sorted(
        f for f in migrations_dir.iterdir() if f.suffix == ".sql" and f.name not in applied
    )

    if not sql_files:
        logger.info("No pending migrations")
        return 0

    count = 0
    for sql_file in sql_files:
        sql = sql_file.read_text(encoding="utf-8")
        async with conn.transaction():
            await conn.execute(sql)
            await conn.execute(
                "INSERT INTO _migrations (filename) VALUES ($1)",
                sql_file.name,
            )
        logger.info("Applied migration: %s", sql_file.name)
        count += 1

    logger.info("Migrations complete: %d applied", count)
    return count
