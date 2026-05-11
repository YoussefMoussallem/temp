"""Memory repository — DB operations for both memory scopes.

Tool-gated memory pattern (see ``project_chat_loop_refactor.md`` and
``agent-loop-architecture.md`` for context): the agent never auto-loads
memory; it calls ``ListUserMemories`` / ``ListProjectMemories`` to
discover what exists, then ``ReadMemory`` to pull bodies. Repository
exposes that surface plus upsert + delete.

All functions take a ``Pool`` and return either the typed dataclass or
``None`` (for misses). No transactions needed — every operation is a
single SQL statement; the upserts handle the read-then-write race via
``ON CONFLICT``.
"""

from __future__ import annotations

from uuid import UUID

from app.db import Pool
from app.db.memories import queries
from app.db.memories.models import ProjectMemory, UserMemory


# ── user_memories ──────────────────────────────────────────────────────────


async def list_user_memories(pool: Pool, user_id: str) -> list[UserMemory]:
    rows = await pool.fetch(queries.USER_LIST, user_id)
    return [UserMemory.from_record(r) for r in rows]


async def get_user_memory(pool: Pool, user_id: str, slug: str) -> UserMemory | None:
    row = await pool.fetchrow(queries.USER_GET, user_id, slug)
    return UserMemory.from_record(row) if row else None


async def upsert_user_memory(
    pool: Pool,
    *,
    user_id: str,
    slug: str,
    type: str,
    name: str,
    description: str,
    body: str,
) -> UserMemory:
    """Insert or update a user-scope memory keyed on (user_id, slug)."""
    row = await pool.fetchrow(
        queries.USER_UPSERT, user_id, slug, type, name, description, body,
    )
    return UserMemory.from_record(row)


async def delete_user_memory(pool: Pool, user_id: str, slug: str) -> None:
    await pool.execute(queries.USER_DELETE, user_id, slug)


# ── project_memories ───────────────────────────────────────────────────────


async def list_project_memories(
    pool: Pool, project_id: UUID,
) -> list[ProjectMemory]:
    rows = await pool.fetch(queries.PROJECT_LIST, project_id)
    return [ProjectMemory.from_record(r) for r in rows]


async def get_project_memory(
    pool: Pool, project_id: UUID, slug: str,
) -> ProjectMemory | None:
    row = await pool.fetchrow(queries.PROJECT_GET, project_id, slug)
    return ProjectMemory.from_record(row) if row else None


async def upsert_project_memory(
    pool: Pool,
    *,
    project_id: UUID,
    slug: str,
    type: str,
    name: str,
    description: str,
    body: str,
    created_by_user_id: str,
) -> ProjectMemory:
    """Insert or update a project-scope memory keyed on (project_id, slug).

    ``created_by_user_id`` is recorded on insert and preserved on update —
    the upsert query intentionally does NOT touch this field in the DO
    UPDATE branch, so attribution sticks with the original author even
    when later edits come from a different collaborator.
    """
    row = await pool.fetchrow(
        queries.PROJECT_UPSERT,
        project_id, slug, type, name, description, body, created_by_user_id,
    )
    return ProjectMemory.from_record(row)


async def delete_project_memory(pool: Pool, project_id: UUID, slug: str) -> None:
    await pool.execute(queries.PROJECT_DELETE, project_id, slug)
