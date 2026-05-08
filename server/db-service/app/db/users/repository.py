"""User repository — all user DB operations."""

from __future__ import annotations

from app.db import Pool
from app.db.users import queries
from app.db.users.models import User


async def get_or_create_user(
    pool: Pool,
    *,
    azure_oid: str,
    email: str,
    display_name: str | None = None,
) -> User:
    """Insert a user or update email/display_name on conflict."""
    row = await pool.fetchrow(queries.UPSERT, azure_oid, email, display_name)
    return User.from_record(row)


async def get_user_by_oid(pool: Pool, azure_oid: str) -> User | None:
    row = await pool.fetchrow(queries.GET_BY_OID, azure_oid)
    return User.from_record(row) if row else None


async def get_user_by_email(pool: Pool, email: str) -> User | None:
    row = await pool.fetchrow(queries.GET_BY_EMAIL, email)
    return User.from_record(row) if row else None


async def get_all_users(pool: Pool) -> list[User]:
    rows = await pool.fetch(queries.GET_ALL)
    return [User.from_record(r) for r in rows]


async def delete_user(pool: Pool, azure_oid: str) -> None:
    """Admin-only: hard-delete a user.

    Cascades through every FK that points at ``users.azure_oid`` —
    usage records, projects they own (and their conversations/
    messages/slides), and any ``project_members`` rows. See
    ``queries.DELETE_USER`` for the full impact list.
    """
    await pool.execute(queries.DELETE_USER, azure_oid)
