"""DB service proxy — forwards DB-service calls through the backend.

Why this exists
---------------
The frontend only talks to the backend (single origin, single auth
surface). Any CRUD the frontend needs against the DB service goes
through this router, which rewrites the path and forwards the caller's
bearer token unchanged. The DB service itself is the authority on
AuthZ - we do not inspect or rewrite the token here.

Shape of a handler
------------------
Every endpoint below is a thin wrapper:
    1. Grab the `Authorization` header (passthrough, not validated here).
    2. Call `_proxy` or `_proxy_get` with the DB-service path.
    3. Return the JSON body.

Error mapping lives in ``_proxy``:
    DB 401/403/404 -> same status bubbled to the client
    DB 5xx / network failure -> 502 Bad Gateway

Adding a new proxied endpoint
-----------------------------
Pick the matching section (Usage / Admin / Projects / Conversations /
Messages), add a handler that calls `_proxy*`, and mirror the DB
service's path + method. Do not add business logic here; this file is
deliberately dumb forwarding.
"""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Body, Header, Query, HTTPException, Response

from app.config import get_settings
from app.bridges import app_settings_client
from app.bridges.db_client import get_my_usage

router = APIRouter(tags=["db"])

# Shared client — keeping a pool of connections to db-service avoids paying
# TCP connect + handshake on every CRUD call (saved per-call latency on
# localhost is small but noticeable; across a network it's significant).
# The client is lazily constructed on first use so import-time side effects
# stay minimal; there is no explicit shutdown hook, which is fine because
# httpx.AsyncClient cleans up on process exit.
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    """Return the process-wide httpx client, creating it on first call."""
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=10)
    return _client


def _db_url() -> str:
    """Base URL of the db-service, without a trailing slash."""
    return get_settings().app.db_service_url.rstrip("/")


async def _proxy(
    method: str,
    path: str,
    authorization: str | None,
    *,
    params: dict | None = None,
    json_body: Any = None,
) -> tuple[int, Any]:
    """Forward a single request to the DB service.

    Returns ``(status_code, body)`` where body is parsed JSON when the
    response has a JSON payload, the raw text if JSON parsing fails, or
    ``None`` for 204 / empty bodies.

    Error handling strategy:
      * Network / connection failure -> raise 502 (caller sees the DB
        service as unavailable, not a 500 from us).
      * DB 401/403/404 -> re-raise with the same status so the frontend
        can react appropriately (e.g. force re-login on 401).
      * DB 5xx -> raise 502; we don't want to surface the DB service's
        internal failures as our own 500s.
      * 2xx / 3xx -> return (status, body) and let the caller decide.
    """
    headers = {}
    if authorization:
        # Passthrough only; the DB service validates the token.
        headers["Authorization"] = authorization
    try:
        resp = await _get_client().request(
            method,
            f"{_db_url()}{path}",
            headers=headers,
            params=params or {},
            json=json_body,
        )
    except Exception:
        # Connection refused, DNS failure, timeout, etc. - treat the DB
        # service as down from the caller's perspective.
        raise HTTPException(status_code=502, detail="DB service unavailable")

    if resp.status_code == 401:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if resp.status_code == 403:
        raise HTTPException(status_code=403, detail=resp.text or "Forbidden")
    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail=resp.text or "Not found")
    if resp.status_code >= 500:
        # Collapse all DB 5xx to 502 - the failure is downstream of us.
        raise HTTPException(status_code=502, detail="DB service error")

    if resp.status_code == 204 or not resp.content:
        return resp.status_code, None
    try:
        return resp.status_code, resp.json()
    except Exception:
        # Non-JSON success body (rare) - hand back the raw text instead
        # of crashing the proxy.
        return resp.status_code, resp.text


async def _proxy_get(path: str, authorization: str | None, params: dict | None = None) -> dict:
    """GET helper: forwards the request and raises on any 4xx/5xx.

    Unlike ``_proxy``, which returns the status so the caller can branch,
    this helper assumes the caller only wants the success body. Use it
    for plain read endpoints.
    """
    status, body = await _proxy("GET", path, authorization, params=params)
    if status >= 400:
        raise HTTPException(status_code=status, detail=str(body))
    return body  # type: ignore[return-value]


def _date_params(start: str | None, end: str | None) -> dict:
    """Build a query-param dict, omitting keys whose value is None/empty.

    Several admin / usage endpoints accept an optional date window.
    Sending ``start=`` with an empty string would be parsed as "filter
    by empty date" on the DB side, so we drop missing values entirely.
    """
    params = {}
    if start:
        params["start"] = start
    if end:
        params["end"] = end
    return params


# ── Usage ──────────────────────────────────────────────────────────────
# Per-user usage stats. `/usage/me` goes through the typed bridge
# (`get_my_usage`) rather than the generic `_proxy_get` because the
# frontend expects a specific empty-state shape on failure.

@router.get("/usage/me")
async def my_usage(
    authorization: str | None = Header(default=None),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
):
    """Return the caller's own token/usage records, optionally date-windowed.

    On DB failure we return an empty-but-valid shape instead of 502 so
    the dashboard can render gracefully. This is a deliberate exception
    to the usual "surface errors upward" rule in this module.
    """
    result = await get_my_usage(authorization or "", start=start, end=end)
    if result is None:
        return {"error": "Failed to fetch usage data", "totals": [], "records": []}
    return result


# ── Admin ──────────────────────────────────────────────────────────────
# AuthZ (is-admin check) is enforced by the DB service; we just forward.

@router.get("/admin/stats")
async def admin_stats(
    authorization: str | None = Header(default=None),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
):
    return await _proxy_get("/api/admin/stats", authorization, _date_params(start, end))


@router.get("/admin/users")
async def admin_users(authorization: str | None = Header(default=None)):
    return await _proxy_get("/api/admin/users", authorization)


@router.get("/admin/usage")
async def admin_usage(
    authorization: str | None = Header(default=None),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
):
    return await _proxy_get("/api/admin/usage", authorization, _date_params(start, end))


# ── Admin: project & user management ──────────────────────────────────────
# Bypasses ``require_project_access`` server-side — the admin doesn't
# need a row in project_members to act on a project. ``get_admin_user``
# is the only gate.

@router.get("/admin/projects")
async def admin_list_projects(authorization: str | None = Header(default=None)):
    return await _proxy_get("/api/admin/projects", authorization)


@router.get("/admin/projects/{project_id}/conversations")
async def admin_list_project_conversations(
    project_id: str,
    authorization: str | None = Header(default=None),
):
    return await _proxy_get(
        f"/api/admin/projects/{project_id}/conversations", authorization,
    )


@router.get("/admin/projects/{project_id}/members")
async def admin_list_project_members(
    project_id: str,
    authorization: str | None = Header(default=None),
):
    return await _proxy_get(
        f"/api/admin/projects/{project_id}/members", authorization,
    )


@router.post("/admin/projects/{project_id}/members", status_code=201)
async def admin_add_project_member(
    project_id: str,
    payload: dict = Body(...),
    authorization: str | None = Header(default=None),
):
    status, body = await _proxy(
        "POST", f"/api/admin/projects/{project_id}/members", authorization,
        json_body=payload,
    )
    if status >= 400:
        raise HTTPException(status_code=status, detail=str(body))
    return body


@router.patch("/admin/projects/{project_id}/members/{member_user_id}")
async def admin_update_member_role(
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


@router.delete(
    "/admin/projects/{project_id}/members/{member_user_id}", status_code=204
)
async def admin_remove_member(
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
async def admin_update_project(
    project_id: str,
    payload: dict = Body(...),
    authorization: str | None = Header(default=None),
):
    status, body = await _proxy(
        "PATCH", f"/api/admin/projects/{project_id}", authorization,
        json_body=payload,
    )
    if status >= 400:
        raise HTTPException(status_code=status, detail=str(body))
    return body


@router.delete("/admin/projects/{project_id}", status_code=204)
async def admin_delete_project(
    project_id: str,
    authorization: str | None = Header(default=None),
):
    await _proxy(
        "DELETE", f"/api/admin/projects/{project_id}", authorization,
    )
    return Response(status_code=204)


@router.post("/admin/projects/{project_id}/transfer")
async def admin_transfer_ownership(
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


# ── Admin: app settings (model defaults) ─────────────────────────────
# Tenant-wide model selection — main / search / export. AuthZ is
# enforced by db-service via ``get_admin_user``; we forward the
# bearer token. The PUT also invalidates the backend's local TTL
# cache so admin changes propagate to in-flight ``/turn`` traffic
# without waiting for the cache to expire.

@router.get("/admin/settings/models")
async def admin_get_model_settings(authorization: str | None = Header(default=None)):
    return await _proxy_get("/api/admin/settings/models", authorization)


@router.put("/admin/settings/models")
async def admin_update_model_settings(
    payload: dict = Body(...),
    authorization: str | None = Header(default=None),
):
    status, body = await _proxy(
        "PUT", "/api/admin/settings/models", authorization,
        json_body=payload,
    )
    if status >= 400:
        raise HTTPException(status_code=status, detail=str(body))
    # Drop the in-process cache so the next /turn / export sees the
    # new defaults without waiting for the TTL window. The db-service
    # Redis cache was already busted inside ``set_setting``.
    app_settings_client.invalidate_cache()
    return body


@router.delete("/admin/users/{azure_oid}", status_code=204)
async def admin_delete_user(
    azure_oid: str,
    authorization: str | None = Header(default=None),
):
    await _proxy("DELETE", f"/api/admin/users/{azure_oid}", authorization)
    return Response(status_code=204)


# ── Projects / Conversations / Messages ───────────────────────────────────
# CRUD for the chat hierarchy: project > conversation > message.
# Ownership is enforced server-side (DB service) via the bearer token.
# Message writes are append-only and happen on the DB service during
# agent turns; this router only exposes reads + project/conversation
# lifecycle.

@router.get("/projects")
async def list_projects(authorization: str | None = Header(default=None)):
    return await _proxy_get("/api/projects", authorization)


@router.post("/projects")
async def create_project(
    payload: dict = Body(...),
    authorization: str | None = Header(default=None),
):
    status, body = await _proxy("POST", "/api/projects", authorization, json_body=payload)
    if status >= 400:
        raise HTTPException(status_code=status, detail=str(body))
    return body


@router.patch("/projects/{project_id}")
async def update_project(
    project_id: str,
    payload: dict = Body(...),
    authorization: str | None = Header(default=None),
):
    status, body = await _proxy(
        "PATCH", f"/api/projects/{project_id}", authorization, json_body=payload,
    )
    if status >= 400:
        raise HTTPException(status_code=status, detail=str(body))
    return body


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(
    project_id: str,
    authorization: str | None = Header(default=None),
):
    await _proxy("DELETE", f"/api/projects/{project_id}", authorization)
    return Response(status_code=204)


# ── Project members ──────────────────────────────────────────────────────
# Sharing endpoints. AuthZ (viewer / editor / owner) is enforced server-side
# by the DB service via require_project_access; we just forward.

@router.get("/projects/{project_id}/members")
async def list_project_members(
    project_id: str,
    authorization: str | None = Header(default=None),
):
    return await _proxy_get(f"/api/projects/{project_id}/members", authorization)


@router.post("/projects/{project_id}/members", status_code=201)
async def add_project_member(
    project_id: str,
    payload: dict = Body(...),
    authorization: str | None = Header(default=None),
):
    status, body = await _proxy(
        "POST", f"/api/projects/{project_id}/members", authorization,
        json_body=payload,
    )
    if status >= 400:
        raise HTTPException(status_code=status, detail=str(body))
    return body


@router.patch("/projects/{project_id}/members/{member_user_id}")
async def update_project_member_role(
    project_id: str,
    member_user_id: str,
    payload: dict = Body(...),
    authorization: str | None = Header(default=None),
):
    status, body = await _proxy(
        "PATCH",
        f"/api/projects/{project_id}/members/{member_user_id}",
        authorization,
        json_body=payload,
    )
    if status >= 400:
        raise HTTPException(status_code=status, detail=str(body))
    return body


@router.delete("/projects/{project_id}/members/{member_user_id}", status_code=204)
async def remove_project_member(
    project_id: str,
    member_user_id: str,
    authorization: str | None = Header(default=None),
):
    await _proxy(
        "DELETE",
        f"/api/projects/{project_id}/members/{member_user_id}",
        authorization,
    )
    return Response(status_code=204)


@router.get("/projects/{project_id}/conversations")
async def list_conversations(
    project_id: str,
    authorization: str | None = Header(default=None),
):
    return await _proxy_get(f"/api/projects/{project_id}/conversations", authorization)


@router.post("/projects/{project_id}/conversations")
async def create_conversation(
    project_id: str,
    payload: dict = Body(...),
    authorization: str | None = Header(default=None),
):
    status, body = await _proxy(
        "POST", f"/api/projects/{project_id}/conversations", authorization,
        json_body=payload,
    )
    if status >= 400:
        raise HTTPException(status_code=status, detail=str(body))
    return body


@router.patch("/conversations/{conversation_id}")
async def update_conversation(
    conversation_id: str,
    payload: dict = Body(...),
    authorization: str | None = Header(default=None),
):
    """Rename a conversation. Body: ``{title: str}``. Forwards directly
    to db-service which enforces editor role + length validation.
    """
    status, body = await _proxy(
        "PATCH", f"/api/conversations/{conversation_id}", authorization,
        json_body=payload,
    )
    if status >= 400:
        raise HTTPException(status_code=status, detail=str(body))
    return body


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: str,
    authorization: str | None = Header(default=None),
):
    await _proxy("DELETE", f"/api/conversations/{conversation_id}", authorization)
    return Response(status_code=204)


@router.get("/conversations/{conversation_id}/messages")
async def list_messages(
    conversation_id: str,
    before_sequence: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    authorization: str | None = Header(default=None),
):
    """Paginated history for a conversation.

    Uses keyset pagination on ``sequence`` (append-only, monotonic per
    conversation). Pass the lowest sequence you already have as
    ``before_sequence`` to fetch the next older page. ``limit`` is
    clamped to [1, 200] to protect the DB.
    """
    params: dict = {"limit": limit}
    if before_sequence is not None:
        params["before_sequence"] = before_sequence
    return await _proxy_get(
        f"/api/conversations/{conversation_id}/messages", authorization, params,
    )


# ── Slides ────────────────────────────────────────────────────────────────
# Project-scoped deck: list + create under /projects/{pid}/slides, patch /
# delete / reorder under /slides/{sid}. Slide tools also hit these via the
# backend's own db_client, so forwarding them through the proxy keeps the
# slide HTTP contract observable from the browser side too.

@router.get("/projects/{project_id}/slides")
async def list_slides(
    project_id: str,
    authorization: str | None = Header(default=None),
):
    return await _proxy_get(f"/api/projects/{project_id}/slides", authorization)


@router.post("/projects/{project_id}/slides")
async def create_slide(
    project_id: str,
    payload: dict = Body(...),
    authorization: str | None = Header(default=None),
):
    status, body = await _proxy(
        "POST", f"/api/projects/{project_id}/slides", authorization,
        json_body=payload,
    )
    if status >= 400:
        raise HTTPException(status_code=status, detail=str(body))
    return body


@router.patch("/slides/{slide_id}")
async def update_slide(
    slide_id: str,
    payload: dict = Body(...),
    authorization: str | None = Header(default=None),
):
    status, body = await _proxy(
        "PATCH", f"/api/slides/{slide_id}", authorization, json_body=payload,
    )
    if status >= 400:
        raise HTTPException(status_code=status, detail=str(body))
    return body


@router.delete("/slides/{slide_id}", status_code=204)
async def delete_slide(
    slide_id: str,
    authorization: str | None = Header(default=None),
):
    await _proxy("DELETE", f"/api/slides/{slide_id}", authorization)
    return Response(status_code=204)


@router.post("/slides/{slide_id}/reorder")
async def reorder_slide(
    slide_id: str,
    payload: dict = Body(...),
    authorization: str | None = Header(default=None),
):
    status, body = await _proxy(
        "POST", f"/api/slides/{slide_id}/reorder", authorization,
        json_body=payload,
    )
    if status >= 400:
        raise HTTPException(status_code=status, detail=str(body))
    return body
