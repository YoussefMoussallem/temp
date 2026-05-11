"""Admin endpoints — protected by separate Azure AD app registration.

Two halves:

* Usage / aggregate stats (existing) — read-only token + cost
  reporting.
* Project & user management (added with sharing) — admins can list
  every project in the system, manage its members, rename / delete /
  transfer ownership of any project, and hard-delete users.

These endpoints deliberately bypass ``require_project_access``: the
admin doesn't need a row in ``project_members`` to act on a project.
``Depends(get_admin_user)`` is the only gate.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel

from app.db import Pool, cache_del, get_pool
from app.db.app_settings.repository import (
    get_all_settings as get_all_app_settings,
    set_setting as set_app_setting,
)
from app.db.project_members.repository import (
    add_member,
    get_member,
    list_member_user_ids,
    list_member_views,
    remove_member,
    update_role,
)
from app.db.conversations.repository import list_conversations_by_project
from app.db.projects.repository import (
    delete_project,
    get_project,
    list_all_projects_with_stats,
    transfer_ownership,
    update_project,
)
from app.db.users.repository import (
    delete_user,
    get_all_users,
    get_user_by_email,
    get_user_by_oid,
)
from app.db.usage_records.repository import (
    get_all_records_with_user,
    get_aggregate_stats,
    get_all_totals,
)
from app.dependencies import CurrentUser, get_admin_user

router = APIRouter(prefix="/admin", tags=["admin"])

_ALLOWED_INVITE_ROLES = {"editor", "viewer"}


def _projects_cache_key(user_id: str) -> str:
    return f"cache:user:{user_id}:projects"


def _conv_list_cache_key(project_id) -> str:
    return f"cache:project:{project_id}:conv_list"


async def _bust_for_all_members(pool: Pool, project_id: UUID) -> None:
    """Invalidate every current member's cached project list."""
    user_ids = await list_member_user_ids(pool, project_id)
    for uid in user_ids:
        cache_del(_projects_cache_key(uid))


def _default_start() -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=30)


def _default_end() -> datetime:
    return datetime.now(timezone.utc)


def _jsonify(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    return value


def _serialize_row(row: dict) -> dict:
    return {k: _jsonify(v) for k, v in row.items()}


def _serialize_obj(obj) -> dict:
    d = asdict(obj) if hasattr(obj, "__dataclass_fields__") else dict(obj)
    return _serialize_row(d)


@router.get("/stats")
async def admin_stats(
    _: CurrentUser = Depends(get_admin_user),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
):
    pool: Pool = await get_pool()
    period_start = start or _default_start()
    period_end = end or _default_end()

    stats = await get_aggregate_stats(pool, start=period_start, end=period_end)
    per_user = await get_all_totals(pool, start=period_start, end=period_end)

    return {
        "period": {"start": period_start.isoformat(), "end": period_end.isoformat()},
        "aggregate": _serialize_row(stats),
        "per_user": [_serialize_row(r) for r in per_user],
    }


@router.get("/users")
async def admin_users(_: CurrentUser = Depends(get_admin_user)):
    pool: Pool = await get_pool()
    users = await get_all_users(pool)
    return {"users": [_serialize_obj(u) for u in users]}


@router.get("/usage")
async def admin_usage_records(
    _: CurrentUser = Depends(get_admin_user),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
):
    pool: Pool = await get_pool()
    period_start = start or _default_start()
    period_end = end or _default_end()

    records = await get_all_records_with_user(pool, start=period_start, end=period_end)
    return {
        "period": {"start": period_start.isoformat(), "end": period_end.isoformat()},
        "records": [_serialize_row(r) for r in records],
    }


# ── Admin: projects ─────────────────────────────────────────────────────


class UpdateProjectRequest(BaseModel):
    name: str | None = None
    description: str | None = None


class AddMemberRequest(BaseModel):
    email: str
    role: str = "viewer"


class UpdateMemberRoleRequest(BaseModel):
    role: str


class TransferOwnershipRequest(BaseModel):
    new_owner_email: str


def _serialize_member(m) -> dict:
    d = asdict(m)
    return _serialize_row(d)


@router.get("/projects")
async def admin_list_projects(_: CurrentUser = Depends(get_admin_user)):
    """Every project in the system with owner email + lifetime token totals.

    Token totals come from ``conversations.total_input_tokens`` /
    ``total_output_tokens`` (lifetime, not date-windowed). A project
    with no conversations shows zero.
    """
    pool: Pool = await get_pool()
    rows = await list_all_projects_with_stats(pool)
    return {"projects": [_serialize_row(r) for r in rows]}


@router.get("/projects/{project_id}/conversations")
async def admin_list_project_conversations(
    project_id: UUID,
    _: CurrentUser = Depends(get_admin_user),
):
    """Every conversation in a project, with running token + cost totals.

    Same shape as the per-conversation rows the regular endpoint returns,
    but bypasses ``require_project_access`` — admins can inspect any
    project's traffic without a membership row.
    """
    pool: Pool = await get_pool()
    project = await get_project(pool, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    conversations = await list_conversations_by_project(pool, project_id)
    return {"conversations": [_serialize_obj(c) for c in conversations]}


@router.get("/projects/{project_id}/members")
async def admin_list_project_members(
    project_id: UUID,
    _: CurrentUser = Depends(get_admin_user),
):
    pool: Pool = await get_pool()
    project = await get_project(pool, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    members = await list_member_views(pool, project_id)
    return {"members": [_serialize_member(m) for m in members]}


@router.post("/projects/{project_id}/members", status_code=201)
async def admin_add_project_member(
    project_id: UUID,
    body: AddMemberRequest,
    _: CurrentUser = Depends(get_admin_user),
):
    if body.role not in _ALLOWED_INVITE_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"Role must be one of {sorted(_ALLOWED_INVITE_ROLES)}",
        )
    pool: Pool = await get_pool()
    project = await get_project(pool, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    invitee = await get_user_by_email(pool, body.email)
    if invitee is None:
        raise HTTPException(
            status_code=404,
            detail="No Edwin user with that email — they need to log in once first.",
        )
    if await get_member(pool, project_id, invitee.azure_oid) is not None:
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


@router.patch("/projects/{project_id}/members/{member_user_id}")
async def admin_update_member_role(
    project_id: UUID,
    member_user_id: str,
    body: UpdateMemberRoleRequest,
    _: CurrentUser = Depends(get_admin_user),
):
    if body.role not in _ALLOWED_INVITE_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"Role must be one of {sorted(_ALLOWED_INVITE_ROLES)}",
        )
    pool: Pool = await get_pool()
    target = await get_member(pool, project_id, member_user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Member not found")
    if target.role == "owner":
        raise HTTPException(
            status_code=400,
            detail="Cannot change the owner's role — use transfer ownership instead.",
        )
    updated = await update_role(pool, project_id, member_user_id, body.role)
    cache_del(_projects_cache_key(member_user_id))
    return _serialize_member(updated)


@router.delete("/projects/{project_id}/members/{member_user_id}", status_code=204)
async def admin_remove_member(
    project_id: UUID,
    member_user_id: str,
    _: CurrentUser = Depends(get_admin_user),
):
    pool: Pool = await get_pool()
    target = await get_member(pool, project_id, member_user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Member not found")
    if target.role == "owner":
        raise HTTPException(
            status_code=400,
            detail="Owner cannot be removed — delete the project or transfer ownership first.",
        )
    await remove_member(pool, project_id, member_user_id)
    cache_del(_projects_cache_key(member_user_id))
    return None


@router.patch("/projects/{project_id}")
async def admin_update_project(
    project_id: UUID,
    body: UpdateProjectRequest,
    _: CurrentUser = Depends(get_admin_user),
):
    pool: Pool = await get_pool()
    project = await get_project(pool, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    updated = await update_project(
        pool, project_id, name=body.name, description=body.description
    )
    await _bust_for_all_members(pool, project_id)
    return _serialize_row(asdict(updated))


@router.delete("/projects/{project_id}", status_code=204)
async def admin_delete_project(
    project_id: UUID,
    _: CurrentUser = Depends(get_admin_user),
):
    pool: Pool = await get_pool()
    project = await get_project(pool, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    # Snapshot members before the cascade wipes project_members.
    member_user_ids = await list_member_user_ids(pool, project_id)
    await delete_project(pool, project_id)
    for uid in member_user_ids:
        cache_del(_projects_cache_key(uid))
    return None


@router.post("/projects/{project_id}/transfer")
async def admin_transfer_ownership(
    project_id: UUID,
    body: TransferOwnershipRequest,
    _: CurrentUser = Depends(get_admin_user),
):
    """Transfer a project to another user. Old owner is demoted to editor."""
    pool: Pool = await get_pool()
    project = await get_project(pool, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    new_owner = await get_user_by_email(pool, body.new_owner_email)
    if new_owner is None:
        raise HTTPException(
            status_code=404,
            detail="No Edwin user with that email — they need to log in once first.",
        )
    updated = await transfer_ownership(
        pool, project_id, new_owner_oid=new_owner.azure_oid
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Project not found")

    # The old owner stays in the project (now as editor) so their list
    # only needs busting because the project's owner badge changed; the
    # new owner now sees this project as 'owner' and possibly for the
    # first time. Bust both, and the old conversation list cache too.
    await _bust_for_all_members(pool, project_id)
    cache_del(_conv_list_cache_key(project_id))
    return _serialize_row(updated)


# ── Admin: users ────────────────────────────────────────────────────────


# ── Admin: app settings (model defaults) ───────────────────────────────
#
# Tenant-wide model selection (main / search / export) used to live
# per-user in the chat UI / browser localStorage. Now it's centrally
# managed here: admin sets one default each, every user inherits.
# The runtime in backend/app/agent/router.py reads these via the
# unauthenticated ``GET /api/settings/models`` (see
# ``app/routers/settings.py``); the admin UI uses the two endpoints
# below to read + update them.

_MODEL_SETTING_KEYS = (
    "default_model",
    "search_model",
    "export_model",
    "title_model",
    "memory_model",
)


class UpdateModelSettingsRequest(BaseModel):
    """At least one of the keys; omitted keys are left unchanged.

    * ``title_model`` is used by the conversation auto-title flow
      (``POST /api/agent/conversations/{id}/generate-title``).
    * ``memory_model`` is used by the memory-structuring endpoint that
      converts plain-text user input into the persisted memory schema
      (``POST /api/agent/memories/from-text``).

    Empty string falls back to ``default_model`` at resolution time,
    same convention as the other auxiliaries.
    """
    default_model: str | None = None
    search_model: str | None = None
    export_model: str | None = None
    title_model: str | None = None
    memory_model: str | None = None


def _as_str(value) -> str:
    """Coerce a stored JSONB value to a string (empty string when missing)."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


@router.get("/settings/models")
async def admin_get_model_settings(_: CurrentUser = Depends(get_admin_user)):
    """Current main-loop / search / export / title model defaults."""
    pool: Pool = await get_pool()
    settings_map = await get_all_app_settings(pool)
    return {key: _as_str(settings_map.get(key)) for key in _MODEL_SETTING_KEYS}


@router.put("/settings/models")
async def admin_update_model_settings(
    body: UpdateModelSettingsRequest,
    user: CurrentUser = Depends(get_admin_user),
):
    """Upsert one or more model defaults. Empty string is allowed and
    treated as "fall back" by the runtime (search / export only).

    Returns the full post-update map so the admin UI doesn't need a
    second GET to refresh.
    """
    pool: Pool = await get_pool()
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(
            status_code=400,
            detail=(
                "At least one of default_model / search_model / export_model / "
                "title_model is required."
            ),
        )
    for key, value in updates.items():
        if key not in _MODEL_SETTING_KEYS:
            # pydantic already filters unknown keys, but defence in depth.
            continue
        if not isinstance(value, str):
            raise HTTPException(
                status_code=400,
                detail=f"{key} must be a string.",
            )
        await set_app_setting(pool, key=key, value=value, updated_by=user.user_id)

    settings_map = await get_all_app_settings(pool)
    return {key: _as_str(settings_map.get(key)) for key in _MODEL_SETTING_KEYS}


@router.delete("/users/{azure_oid}", status_code=204)
async def admin_delete_user(
    azure_oid: str,
    _: CurrentUser = Depends(get_admin_user),
):
    """Hard-delete a user. Cascades through every owned project + records.

    Anything they merely participated in (other people's projects)
    stays — only their membership row is removed by the FK cascade on
    ``project_members``.
    """
    pool: Pool = await get_pool()
    target = await get_user_by_oid(pool, azure_oid)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    await delete_user(pool, azure_oid)
    # We don't know which project lists this user appeared in (their
    # owned projects are gone), so we can't surgically bust caches.
    # Keys expire on TTL or get clobbered the next time anyone mutates
    # one of the affected projects — acceptable for an admin action.
    return None
