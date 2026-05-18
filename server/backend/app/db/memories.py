"""Memories — long-term agent memory, user-scoped + project-scoped.

Phase 1, tool-gated retrieval. Same critical-path error policy as
slides: every typed-client response goes through ``_check_response``
so 4xx detail strings reach the agent loop as actionable ValueErrors.
Phase 1 covers list / get / upsert / delete for both scopes; no
update endpoint distinct from upsert because the common path is
"save by slug, overwrite if exists."

FE proxy covers list / upsert / delete (no `get` proxy because the
list response already includes bodies).
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Body, Header, HTTPException, Response

from ._shared import _check_response, _get_base_url
from ._shared_proxy import _proxy, _proxy_get


# ===========================================================================
# Typed client — used by memory tools + the /memories/from-text route
# ===========================================================================
# User-scoped


async def list_user_memories(authorization: str, user_oid: str) -> list[dict]:
    """Return the index of a user's memories (slugs + descriptions + bodies).

    Bodies are included by the underlying endpoint but the model-facing
    tool projects to {slug, type, name, description} to keep the
    streamed result small.
    """
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{_get_base_url()}/api/users/{user_oid}/memories",
            headers={"Authorization": authorization},
        )
        _check_response(resp)
        return resp.json().get("memories", [])


async def get_user_memory(
    authorization: str,
    user_oid: str,
    slug: str,
) -> dict | None:
    """Fetch one user memory by slug. Returns None on 404."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{_get_base_url()}/api/users/{user_oid}/memories/{slug}",
            headers={"Authorization": authorization},
        )
        if resp.status_code == 404:
            return None
        _check_response(resp)
        return resp.json()


async def upsert_user_memory(
    authorization: str,
    user_oid: str,
    *,
    slug: str,
    type: str,
    name: str,
    description: str,
    body: str,
) -> dict:
    """Insert or update a user memory by slug."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{_get_base_url()}/api/users/{user_oid}/memories",
            headers={"Authorization": authorization},
            json={
                "slug": slug,
                "type": type,
                "name": name,
                "description": description,
                "body": body,
            },
        )
        _check_response(resp)
        return resp.json()


async def delete_user_memory(
    authorization: str,
    user_oid: str,
    slug: str,
) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.delete(
            f"{_get_base_url()}/api/users/{user_oid}/memories/{slug}",
            headers={"Authorization": authorization},
        )
        _check_response(resp)


# Project-scoped


async def list_project_memories(
    authorization: str,
    project_id: str,
) -> list[dict]:
    """Return the index of a project's memories."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{_get_base_url()}/api/projects/{project_id}/memories",
            headers={"Authorization": authorization},
        )
        _check_response(resp)
        return resp.json().get("memories", [])


async def get_project_memory(
    authorization: str,
    project_id: str,
    slug: str,
) -> dict | None:
    """Fetch one project memory by slug. Returns None on 404."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{_get_base_url()}/api/projects/{project_id}/memories/{slug}",
            headers={"Authorization": authorization},
        )
        if resp.status_code == 404:
            return None
        _check_response(resp)
        return resp.json()


async def upsert_project_memory(
    authorization: str,
    project_id: str,
    *,
    slug: str,
    type: str,
    name: str,
    description: str,
    body: str,
) -> dict:
    """Insert or update a project memory by slug. The DB service records
    ``created_by_user_id`` from the JWT — we don't pass it explicitly."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{_get_base_url()}/api/projects/{project_id}/memories",
            headers={"Authorization": authorization},
            json={
                "slug": slug,
                "type": type,
                "name": name,
                "description": description,
                "body": body,
            },
        )
        _check_response(resp)
        return resp.json()


async def delete_project_memory(
    authorization: str,
    project_id: str,
    slug: str,
) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.delete(
            f"{_get_base_url()}/api/projects/{project_id}/memories/{slug}",
            headers={"Authorization": authorization},
        )
        _check_response(resp)
        resp.raise_for_status()


# ===========================================================================
# FastAPI router — FE proxy
# ===========================================================================
# AuthZ enforced by db-service: user-scope endpoints require the caller's
# own azure_oid; project-scope endpoints require_project_access.

router = APIRouter(tags=["db"])


@router.get("/users/{azure_oid}/memories")
async def _route_list_user_memories(
    azure_oid: str,
    authorization: str | None = Header(default=None),
):
    return await _proxy_get(f"/api/users/{azure_oid}/memories", authorization)


@router.post("/users/{azure_oid}/memories")
async def _route_upsert_user_memory(
    azure_oid: str,
    payload: dict = Body(...),
    authorization: str | None = Header(default=None),
):
    status, body = await _proxy(
        "POST",
        f"/api/users/{azure_oid}/memories",
        authorization,
        json_body=payload,
    )
    if status >= 400:
        raise HTTPException(status_code=status, detail=str(body))
    return body


@router.delete("/users/{azure_oid}/memories/{slug}", status_code=204)
async def _route_delete_user_memory(
    azure_oid: str,
    slug: str,
    authorization: str | None = Header(default=None),
):
    await _proxy("DELETE", f"/api/users/{azure_oid}/memories/{slug}", authorization)
    return Response(status_code=204)


@router.get("/projects/{project_id}/memories")
async def _route_list_project_memories(
    project_id: str,
    authorization: str | None = Header(default=None),
):
    return await _proxy_get(f"/api/projects/{project_id}/memories", authorization)


@router.post("/projects/{project_id}/memories")
async def _route_upsert_project_memory(
    project_id: str,
    payload: dict = Body(...),
    authorization: str | None = Header(default=None),
):
    status, body = await _proxy(
        "POST",
        f"/api/projects/{project_id}/memories",
        authorization,
        json_body=payload,
    )
    if status >= 400:
        raise HTTPException(status_code=status, detail=str(body))
    return body


@router.delete("/projects/{project_id}/memories/{slug}", status_code=204)
async def _route_delete_project_memory(
    project_id: str,
    slug: str,
    authorization: str | None = Header(default=None),
):
    await _proxy("DELETE", f"/api/projects/{project_id}/memories/{slug}", authorization)
    return Response(status_code=204)
