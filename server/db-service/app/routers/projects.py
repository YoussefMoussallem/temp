"""Project CRUD + member-management endpoints.

Authorization
-------------
Every endpoint goes through ``require_project_access`` (in
``app/db/projects/access.py``). It returns the caller's role on the
project and raises 404 if they have no membership at all (which
deliberately doesn't leak whether the project exists).

Roles required per operation:

| Operation                              | Min role |
|----------------------------------------|----------|
| GET   /projects                        | (any membership)   |
| POST  /projects                        | (any authenticated user — they become owner) |
| PATCH /projects/{id}                   | editor   |
| DELETE /projects/{id}                  | owner    |
| GET   /projects/{id}/members           | viewer   |
| POST  /projects/{id}/members           | owner    |
| PATCH /projects/{id}/members/{user_id} | owner    |
| DELETE /projects/{id}/members/{user_id}| owner OR self |

Cache
-----
``cache:user:{user_id}:projects`` holds each user's project list.
Membership-change endpoints invalidate the affected member's key (and
the caller's, when they're not the same person). Project rename / delete
fan out to every current member.
"""

from __future__ import annotations

from dataclasses import asdict
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.db import Pool, cache_del, cache_get_json, cache_set_json, get_pool
from app.db.project_members.repository import (
    add_member,
    get_member,
    list_member_user_ids,
    list_member_views,
    remove_member,
    update_role,
)
from app.db.projects.access import require_project_access, role_meets
from app.db.projects.repository import (
    create_project,
    delete_project,
    update_project,
    list_projects_by_user,
)
from app.db.users.repository import get_user_by_email
from app.dependencies import CurrentUser, get_current_user

router = APIRouter(prefix="/projects", tags=["projects"])


def _projects_cache_key(user_id: str) -> str:
    return f"cache:user:{user_id}:projects"


_ALLOWED_INVITE_ROLES = {"editor", "viewer"}


class CreateProjectRequest(BaseModel):
    name: str
    description: str | None = None


class UpdateProjectRequest(BaseModel):
    name: str | None = None
    description: str | None = None


class AddMemberRequest(BaseModel):
    email: str
    role: str = "viewer"


class UpdateMemberRoleRequest(BaseModel):
    role: str


def _serialize(project) -> dict:
    d = asdict(project)
    for k, v in d.items():
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
        elif isinstance(v, UUID):
            d[k] = str(v)
    return d


def _serialize_member(member) -> dict:
    d = asdict(member)
    for k, v in d.items():
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
        elif isinstance(v, UUID):
            d[k] = str(v)
    return d


async def _invalidate_for_all_members(pool: Pool, project_id: UUID) -> None:
    """Bust the project-list cache for every current member of a project.

    Used when a project is renamed / deleted — the cached row appears in
    each member's list and needs to disappear or refresh.
    """
    user_ids = await list_member_user_ids(pool, project_id)
    for uid in user_ids:
        cache_del(_projects_cache_key(uid))


# ── Project CRUD ───────────────────────────────────────────────────────────


@router.get("")
async def list_projects(user: CurrentUser = Depends(get_current_user)):
    """List projects the caller is a member of (owner / editor / viewer)."""
    key = _projects_cache_key(user.azure_oid)
    cached = await cache_get_json(key)
    if cached is not None:
        return {"projects": cached}

    pool: Pool = await get_pool()
    projects = await list_projects_by_user(pool, user.azure_oid)
    payload = [_serialize(p) for p in projects]
    cache_set_json(key, payload)
    return {"projects": payload}


@router.post("")
async def create(
    body: CreateProjectRequest,
    user: CurrentUser = Depends(get_current_user),
):
    """Create a project. The caller becomes its sole 'owner' member."""
    pool: Pool = await get_pool()
    project = await create_project(
        pool, user_id=user.azure_oid, name=body.name, description=body.description
    )
    cache_del(_projects_cache_key(user.azure_oid))
    return _serialize(project)


@router.patch("/{project_id}")
async def patch(
    project_id: UUID,
    body: UpdateProjectRequest,
    user: CurrentUser = Depends(get_current_user),
):
    pool: Pool = await get_pool()
    await require_project_access(pool, project_id, user, min_role="editor")
    project = await update_project(pool, project_id, name=body.name, description=body.description)
    # Name/description appear in every member's cached list — fan out.
    await _invalidate_for_all_members(pool, project_id)
    return _serialize(project)


@router.delete("/{project_id}", status_code=204)
async def delete(
    project_id: UUID,
    user: CurrentUser = Depends(get_current_user),
):
    pool: Pool = await get_pool()
    await require_project_access(pool, project_id, user, min_role="owner")
    # Snapshot members BEFORE delete — once the project row goes, the
    # ON DELETE CASCADE empties project_members and we lose the list.
    member_user_ids = await list_member_user_ids(pool, project_id)
    await delete_project(pool, project_id)
    for uid in member_user_ids:
        cache_del(_projects_cache_key(uid))
    return None


# ── Member management ─────────────────────────────────────────────────────


@router.get("/{project_id}/members")
async def list_members(
    project_id: UUID,
    user: CurrentUser = Depends(get_current_user),
):
    """List members of a project (anyone with access can see who else has access)."""
    pool: Pool = await get_pool()
    await require_project_access(pool, project_id, user, min_role="viewer")
    members = await list_member_views(pool, project_id)
    return {"members": [_serialize_member(m) for m in members]}


@router.post("/{project_id}/members", status_code=201)
async def add_project_member(
    project_id: UUID,
    body: AddMemberRequest,
    user: CurrentUser = Depends(get_current_user),
):
    """Invite a user to a project by email. Owner-only.

    Returns 404 if the email isn't a known Edwin user (i.e. they've
    never logged in). We don't auto-create stub users — without a real
    Azure OID there's no way to bind their future logins to this row.
    Returns 409 if the user is already a member.
    """
    if body.role not in _ALLOWED_INVITE_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"Role must be one of {sorted(_ALLOWED_INVITE_ROLES)}",
        )

    pool: Pool = await get_pool()
    await require_project_access(pool, project_id, user, min_role="owner")

    invitee = await get_user_by_email(pool, body.email)
    if invitee is None:
        raise HTTPException(
            status_code=404,
            detail="No Edwin user with that email — they need to log in once first.",
        )

    existing = await get_member(pool, project_id, invitee.azure_oid)
    if existing is not None:
        raise HTTPException(status_code=409, detail="User is already a member")

    member = await add_member(
        pool, project_id=project_id, user_id=invitee.azure_oid, role=body.role
    )
    cache_del(_projects_cache_key(invitee.azure_oid))
    return {
        "user_id": member.user_id,
        "project_id": str(member.project_id),
        "role": member.role,
        "joined_at": member.joined_at.isoformat(),
        "email": invitee.email,
        "display_name": invitee.display_name,
    }


@router.patch("/{project_id}/members/{member_user_id}")
async def patch_member_role(
    project_id: UUID,
    member_user_id: str,
    body: UpdateMemberRoleRequest,
    user: CurrentUser = Depends(get_current_user),
):
    """Change a member's role. Owner-only. Cannot demote the owner."""
    if body.role not in _ALLOWED_INVITE_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"Role must be one of {sorted(_ALLOWED_INVITE_ROLES)}",
        )

    pool: Pool = await get_pool()
    await require_project_access(pool, project_id, user, min_role="owner")

    target = await get_member(pool, project_id, member_user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Member not found")
    if target.role == "owner":
        raise HTTPException(status_code=400, detail="Cannot change the owner's role")

    updated = await update_role(pool, project_id, member_user_id, body.role)
    cache_del(_projects_cache_key(member_user_id))
    return _serialize_member(updated)


@router.delete("/{project_id}/members/{member_user_id}", status_code=204)
async def delete_project_member(
    project_id: UUID,
    member_user_id: str,
    user: CurrentUser = Depends(get_current_user),
):
    """Remove a member. Allowed if the caller is the owner OR is removing themselves.

    Cannot remove the owner via this endpoint — owners must DELETE the
    whole project.
    """
    pool: Pool = await get_pool()
    caller_role = await require_project_access(pool, project_id, user, min_role="viewer")

    is_self = member_user_id == user.azure_oid
    is_owner = role_meets(caller_role, min_role="owner")
    if not (is_self or is_owner):
        raise HTTPException(status_code=403, detail="Only the owner can remove other members")

    target = await get_member(pool, project_id, member_user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Member not found")
    if target.role == "owner":
        raise HTTPException(
            status_code=400,
            detail="Owner cannot be removed; delete the project instead",
        )

    await remove_member(pool, project_id, member_user_id)
    cache_del(_projects_cache_key(member_user_id))
    return None
