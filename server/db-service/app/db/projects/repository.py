"""Project repository — all projects DB operations.

``create_project`` runs as a single transaction: it inserts the project
row AND inserts the owner's ``project_members`` row (role='owner'). The
two are kept in lockstep so ``list_projects_by_user`` (which JOINs
``project_members``) always sees a project's owner.
"""

from __future__ import annotations

from uuid import UUID

from app.db import Pool
from app.db.projects import queries
from app.db.projects.models import Project
from app.db.project_members import queries as member_queries


async def create_project(
    pool: Pool,
    *,
    user_id: str,
    name: str,
    description: str | None = None,
) -> Project:
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(queries.INSERT, user_id, name, description)
            project = Project.from_record(row)
            await conn.execute(
                member_queries.INSERT, user_id, project.id, "owner"
            )
    return project


async def get_project(pool: Pool, project_id: UUID) -> Project | None:
    row = await pool.fetchrow(queries.GET, project_id)
    return Project.from_record(row) if row else None


async def list_projects_by_user(pool: Pool, user_id: str) -> list[Project]:
    rows = await pool.fetch(queries.LIST_BY_USER, user_id)
    return [Project.from_record(r) for r in rows]


async def update_project(
    pool: Pool,
    project_id: UUID,
    *,
    name: str | None = None,
    description: str | None = None,
) -> Project | None:
    row = await pool.fetchrow(queries.UPDATE, project_id, name, description)
    return Project.from_record(row) if row else None


async def delete_project(pool: Pool, project_id: UUID) -> None:
    await pool.execute(queries.DELETE, project_id)


async def list_all_projects_with_stats(pool: Pool) -> list[dict]:
    """Admin-only: every project in the system + lifetime token totals.

    Returns a list of plain dicts (not ``Project`` instances) because the
    shape includes columns ``Project`` doesn't model — owner email,
    member count, summed token counters across the project's
    conversations. The router serializes them directly.
    """
    rows = await pool.fetch(queries.LIST_ALL_WITH_STATS)
    return [dict(r) for r in rows]


async def transfer_ownership(
    pool: Pool, project_id: UUID, *, new_owner_oid: str
) -> dict | None:
    """Atomically transfer a project from its current owner to another user.

    Three steps inside one transaction:
      1. Read the current ``projects.user_id`` (old owner).
      2. ``UPDATE projects`` to point at the new owner.
      3. Demote old owner's ``project_members`` row to ``editor`` so they
         keep access; upsert the new owner's row to ``owner``.

    No-ops (returns existing project) if ``new_owner_oid`` is already
    the owner. Returns ``None`` if the project doesn't exist.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            current = await conn.fetchrow(queries.GET, project_id)
            if current is None:
                return None
            old_owner_oid = current["user_id"]
            if old_owner_oid == new_owner_oid:
                return dict(current)

            updated = await conn.fetchrow(
                queries.TRANSFER_OWNER, project_id, new_owner_oid
            )
            await conn.execute(
                member_queries.DEMOTE_OWNER_TO_EDITOR, project_id, old_owner_oid
            )
            await conn.fetchrow(
                member_queries.UPSERT_AS_OWNER, new_owner_oid, project_id
            )
    return dict(updated)
