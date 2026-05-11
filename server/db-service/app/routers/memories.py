"""Memory CRUD endpoints — two scopes, two route trees.

User-scope memory is row-locked to the authenticated user (no admin
override on read/write — even admins can't read another user's
personal memory through this surface). Project-scope memory inherits
the project's existing access model via ``require_project_access``:

| Route                                              | Min role / scope                 |
|----------------------------------------------------|----------------------------------|
| GET    /users/{azure_oid}/memories                 | caller is that user              |
| GET    /users/{azure_oid}/memories/{slug}          | caller is that user              |
| POST   /users/{azure_oid}/memories                 | caller is that user              |
| DELETE /users/{azure_oid}/memories/{slug}          | caller is that user              |
| GET    /projects/{project_id}/memories             | project viewer                   |
| GET    /projects/{project_id}/memories/{slug}      | project viewer                   |
| POST   /projects/{project_id}/memories             | project editor                   |
| DELETE /projects/{project_id}/memories/{slug}      | project editor                   |

Upserts (POST) are idempotent on the scope-+-slug unique constraint so
re-saving the same slug overwrites in place — common when the model
refines an earlier entry.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.db import Pool, get_pool
from app.db.memories.repository import (
    delete_project_memory,
    delete_user_memory,
    get_project_memory,
    get_user_memory,
    list_project_memories,
    list_user_memories,
    upsert_project_memory,
    upsert_user_memory,
)
from app.db.projects.access import require_project_access
from app.dependencies import CurrentUser, get_current_user

router = APIRouter(tags=["memories"])


# ── Request bodies ─────────────────────────────────────────────────────────


class UpsertUserMemoryRequest(BaseModel):
    slug: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")
    type: Literal["user", "feedback", "reference"]
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=150)
    body: str = Field(min_length=1)


class UpsertProjectMemoryRequest(BaseModel):
    slug: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")
    type: Literal["project", "reference", "stakeholder", "decision"]
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=150)
    body: str = Field(min_length=1)


# ── Serialization ──────────────────────────────────────────────────────────


def _serialize(memory) -> dict:
    """Dataclass → JSON-safe dict. Mirrors ``slides._serialize``."""
    d = asdict(memory)
    for k, v in d.items():
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
        elif isinstance(v, UUID):
            d[k] = str(v)
    return d


def _require_self(azure_oid: str, user: CurrentUser) -> None:
    """User-scope memory is private — only the user themselves can touch it.

    Distinct from the project-scope path which uses role-based access. We
    don't even let admins peek at another user's memory through this API;
    if support access is ever needed it should go through a separate
    admin endpoint with explicit audit logging.
    """
    if user.user_id != azure_oid:
        raise HTTPException(status_code=403, detail="Not your memory")


# ── User-scope routes ──────────────────────────────────────────────────────


@router.get("/users/{azure_oid}/memories")
async def list_user_memories_route(
    azure_oid: str,
    user: CurrentUser = Depends(get_current_user),
):
    _require_self(azure_oid, user)
    pool: Pool = await get_pool()
    rows = await list_user_memories(pool, azure_oid)
    return {"memories": [_serialize(r) for r in rows]}


@router.get("/users/{azure_oid}/memories/{slug}")
async def get_user_memory_route(
    azure_oid: str,
    slug: str,
    user: CurrentUser = Depends(get_current_user),
):
    _require_self(azure_oid, user)
    pool: Pool = await get_pool()
    row = await get_user_memory(pool, azure_oid, slug)
    if row is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    return _serialize(row)


@router.post("/users/{azure_oid}/memories")
async def upsert_user_memory_route(
    azure_oid: str,
    body: UpsertUserMemoryRequest,
    user: CurrentUser = Depends(get_current_user),
):
    _require_self(azure_oid, user)
    pool: Pool = await get_pool()
    row = await upsert_user_memory(
        pool,
        user_id=azure_oid,
        slug=body.slug,
        type=body.type,
        name=body.name,
        description=body.description,
        body=body.body,
    )
    return _serialize(row)


@router.delete("/users/{azure_oid}/memories/{slug}", status_code=204)
async def delete_user_memory_route(
    azure_oid: str,
    slug: str,
    user: CurrentUser = Depends(get_current_user),
):
    _require_self(azure_oid, user)
    pool: Pool = await get_pool()
    await delete_user_memory(pool, azure_oid, slug)
    return None


# ── Project-scope routes ───────────────────────────────────────────────────


@router.get("/projects/{project_id}/memories")
async def list_project_memories_route(
    project_id: UUID,
    user: CurrentUser = Depends(get_current_user),
):
    pool: Pool = await get_pool()
    await require_project_access(pool, project_id, user, min_role="viewer")
    rows = await list_project_memories(pool, project_id)
    return {"memories": [_serialize(r) for r in rows]}


@router.get("/projects/{project_id}/memories/{slug}")
async def get_project_memory_route(
    project_id: UUID,
    slug: str,
    user: CurrentUser = Depends(get_current_user),
):
    pool: Pool = await get_pool()
    await require_project_access(pool, project_id, user, min_role="viewer")
    row = await get_project_memory(pool, project_id, slug)
    if row is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    return _serialize(row)


@router.post("/projects/{project_id}/memories")
async def upsert_project_memory_route(
    project_id: UUID,
    body: UpsertProjectMemoryRequest,
    user: CurrentUser = Depends(get_current_user),
):
    pool: Pool = await get_pool()
    await require_project_access(pool, project_id, user, min_role="editor")
    row = await upsert_project_memory(
        pool,
        project_id=project_id,
        slug=body.slug,
        type=body.type,
        name=body.name,
        description=body.description,
        body=body.body,
        created_by_user_id=user.user_id,
    )
    return _serialize(row)


@router.delete("/projects/{project_id}/memories/{slug}", status_code=204)
async def delete_project_memory_route(
    project_id: UUID,
    slug: str,
    user: CurrentUser = Depends(get_current_user),
):
    pool: Pool = await get_pool()
    await require_project_access(pool, project_id, user, min_role="editor")
    await delete_project_memory(pool, project_id, slug)
    return None
