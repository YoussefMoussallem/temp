"""Admin — FE proxy only.

Admin endpoints are exposed exclusively for the admin dashboard
frontend. No typed-client surface because backend code never calls
admin endpoints (admin operations are always user-initiated).

AuthZ (is-admin check) is enforced by the db-service; this router
just forwards the bearer token.

Sections:
  * Read-only: /admin/stats, /admin/users, /admin/usage
  * Projects: list / patch / delete / transfer ownership
  * Members: add / patch role / remove
  * Settings: get/put model defaults (PUT invalidates the in-process
    settings cache on success so admin changes propagate without TTL wait)
  * Users: delete
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Header, HTTPException, Query, Response

from app.bridges import app_settings_client

from ._shared_proxy import _date_params, _proxy, _proxy_get

router = APIRouter(tags=["db"])


# ── Read-only stats ───────────────────────────────────────────────────────


@router.get("/admin/stats")
async def _route_admin_stats(
    authorization: str | None = Header(default=None),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
):
    return await _proxy_get("/api/admin/stats", authorization, _date_params(start, end))


@router.get("/admin/users")
async def _route_admin_users(authorization: str | None = Header(default=None)):
    return await _proxy_get("/api/admin/users", authorization)


@router.get("/admin/usage")
async def _route_admin_usage(
    authorization: str | None = Header(default=None),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
):
    return await _proxy_get("/api/admin/usage", authorization, _date_params(start, end))


# ── Project & member management ──────────────────────────────────────────
# Bypasses ``require_project_access`` server-side — the admin doesn't
# need a row in project_members to act on a project. ``get_admin_user``
# is the only gate.


@router.get("/admin/projects")
async def _route_admin_list_projects(authorization: str | None = Header(default=None)):
    return await _proxy_get("/api/admin/projects", authorization)


@router.get("/admin/projects/{project_id}/conversations")
async def _route_admin_list_project_conversations(
    project_id: str,
    authorization: str | None = Header(default=None),
):
    return await _proxy_get(
        f"/api/admin/projects/{project_id}/conversations",
        authorization,
    )


@router.get("/admin/projects/{project_id}/members")
async def _route_admin_list_project_members(
    project_id: str,
    authorization: str | None = Header(default=None),
):
    return await _proxy_get(
        f"/api/admin/projects/{project_id}/members",
        authorization,
    )


@router.post("/admin/projects/{project_id}/members", status_code=201)
async def _route_admin_add_project_member(
    project_id: str,
    payload: dict = Body(...),
    authorization: str | None = Header(default=None),
):
    status, body = await _proxy(
        "POST",
        f"/api/admin/projects/{project_id}/members",
        authorization,
        json_body=payload,
    )
    if status >= 400:
        raise HTTPException(status_code=status, detail=str(body))
    return body


@router.patch("/admin/projects/{project_id}/members/{member_user_id}")
async def _route_admin_update_member_role(
    project_id: str,
    member_user_id: str,
    payload: dict = Body(...),
    authorization: str | None = Header(default=None),
):
    status, body = await _proxy(
        "PATCH",
        f"/api/admin/projects/{project_id}/members/{member_user_id}",
        authorization,
        json_body=payload,
    )
    if status >= 400:
        raise HTTPException(status_code=status, detail=str(body))
    return body


@router.delete("/admin/projects/{project_id}/members/{member_user_id}", status_code=204)
async def _route_admin_remove_member(
    project_id: str,
    member_user_id: str,
    authorization: str | None = Header(default=None),
):
    await _proxy(
        "DELETE",
        f"/api/admin/projects/{project_id}/members/{member_user_id}",
        authorization,
    )
    return Response(status_code=204)


@router.patch("/admin/projects/{project_id}")
async def _route_admin_update_project(
    project_id: str,
    payload: dict = Body(...),
    authorization: str | None = Header(default=None),
):
    status, body = await _proxy(
        "PATCH",
        f"/api/admin/projects/{project_id}",
        authorization,
        json_body=payload,
    )
    if status >= 400:
        raise HTTPException(status_code=status, detail=str(body))
    return body


@router.delete("/admin/projects/{project_id}", status_code=204)
async def _route_admin_delete_project(
    project_id: str,
    authorization: str | None = Header(default=None),
):
    await _proxy(
        "DELETE",
        f"/api/admin/projects/{project_id}",
        authorization,
    )
    return Response(status_code=204)


@router.post("/admin/projects/{project_id}/transfer")
async def _route_admin_transfer_ownership(
    project_id: str,
    payload: dict = Body(...),
    authorization: str | None = Header(default=None),
):
    status, body = await _proxy(
        "POST",
        f"/api/admin/projects/{project_id}/transfer",
        authorization,
        json_body=payload,
    )
    if status >= 400:
        raise HTTPException(status_code=status, detail=str(body))
    return body


# ── App settings (model defaults) ────────────────────────────────────────
# Tenant-wide model selection — main / search / export. AuthZ is
# enforced by db-service via ``get_admin_user``; we forward the
# bearer token. The PUT also invalidates the backend's local TTL
# cache so admin changes propagate to in-flight ``/turn`` traffic
# without waiting for the cache to expire.


@router.get("/admin/settings/models")
async def _route_admin_get_model_settings(authorization: str | None = Header(default=None)):
    return await _proxy_get("/api/admin/settings/models", authorization)


@router.put("/admin/settings/models")
async def _route_admin_update_model_settings(
    payload: dict = Body(...),
    authorization: str | None = Header(default=None),
):
    status, body = await _proxy(
        "PUT",
        "/api/admin/settings/models",
        authorization,
        json_body=payload,
    )
    if status >= 400:
        raise HTTPException(status_code=status, detail=str(body))
    # Drop the in-process cache so the next /turn / export sees the
    # new defaults without waiting for the TTL window. The db-service
    # Redis cache was already busted inside ``set_setting``.
    app_settings_client.invalidate_cache()
    return body


# ── Users ────────────────────────────────────────────────────────────────


@router.delete("/admin/users/{azure_oid}", status_code=204)
async def _route_admin_delete_user(
    azure_oid: str,
    authorization: str | None = Header(default=None),
):
    await _proxy("DELETE", f"/api/admin/users/{azure_oid}", authorization)
    return Response(status_code=204)
