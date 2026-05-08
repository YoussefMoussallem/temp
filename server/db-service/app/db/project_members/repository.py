"""Project-members repository — DB ops for the project_members table.

The owner of a project is stored here as a row with ``role='owner'`` AND
denormalized into ``projects.user_id``. ``create_project`` writes both in a
single transaction so the two never drift.
"""

from __future__ import annotations

from uuid import UUID

from app.db import Pool
from app.db.project_members import queries
from app.db.project_members.models import MemberView, ProjectMember


async def add_member(
    pool: Pool,
    *,
    project_id: UUID,
    user_id: str,
    role: str,
) -> ProjectMember:
    row = await pool.fetchrow(queries.INSERT, user_id, project_id, role)
    return ProjectMember.from_record(row)


async def get_member(
    pool: Pool, project_id: UUID, user_id: str
) -> ProjectMember | None:
    row = await pool.fetchrow(queries.GET, project_id, user_id)
    return ProjectMember.from_record(row) if row else None


async def get_role(pool: Pool, project_id: UUID, user_id: str) -> str | None:
    """Return the caller's role on a project, or None if no membership."""
    return await pool.fetchval(queries.GET_ROLE, project_id, user_id)


async def list_member_views(pool: Pool, project_id: UUID) -> list[MemberView]:
    rows = await pool.fetch(queries.LIST_VIEWS_BY_PROJECT, project_id)
    return [MemberView.from_record(r) for r in rows]


async def list_member_user_ids(pool: Pool, project_id: UUID) -> list[str]:
    """Used for cache invalidation across all members' project lists."""
    rows = await pool.fetch(queries.LIST_USER_IDS_BY_PROJECT, project_id)
    return [r["user_id"] for r in rows]


async def update_role(
    pool: Pool, project_id: UUID, user_id: str, role: str
) -> ProjectMember | None:
    row = await pool.fetchrow(queries.UPDATE_ROLE, project_id, user_id, role)
    return ProjectMember.from_record(row) if row else None


async def remove_member(pool: Pool, project_id: UUID, user_id: str) -> None:
    await pool.execute(queries.DELETE, project_id, user_id)
