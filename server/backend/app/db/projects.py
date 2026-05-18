"""Projects — CRUD + member management.

Typed client (used by backend code) covers project CRUD only.
FE proxy router covers both project CRUD and member management
(member ops are exclusively FE-driven; backend never invites/removes
members on its own).
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Body, Header, HTTPException, Response

from ._shared import _check_response, _get_base_url
from ._shared_proxy import _proxy, _proxy_get


# ===========================================================================
# Typed client — project CRUD only (member ops are FE-only, see router below)
# ===========================================================================


async def list_projects(authorization: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{_get_base_url()}/api/projects",
            headers={"Authorization": authorization},
        )
        _check_response(resp)
        return resp.json().get("projects", [])


async def create_project(authorization: str, *, name: str, description: str | None = None) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{_get_base_url()}/api/projects",
            headers={"Authorization": authorization},
            json={"name": name, "description": description},
        )
        _check_response(resp)
        return resp.json()


async def update_project(
    authorization: str,
    project_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.patch(
            f"{_get_base_url()}/api/projects/{project_id}",
            headers={"Authorization": authorization},
            json={"name": name, "description": description},
        )
        _check_response(resp)
        return resp.json()


async def delete_project(authorization: str, project_id: str) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.delete(
            f"{_get_base_url()}/api/projects/{project_id}",
            headers={"Authorization": authorization},
        )
        _check_response(resp)


# ===========================================================================
# FastAPI router — FE proxy (mounted at /api/db/projects/...)
# ===========================================================================
# Sharing endpoints. AuthZ (viewer / editor / owner) is enforced server-side
# by the DB service via require_project_access; we just forward.

router = APIRouter(tags=["db"])


@router.get("/projects")
async def _route_list_projects(authorization: str | None = Header(default=None)):
    return await _proxy_get("/api/projects", authorization)


@router.post("/projects")
async def _route_create_project(
    payload: dict = Body(...),
    authorization: str | None = Header(default=None),
):
    status, body = await _proxy("POST", "/api/projects", authorization, json_body=payload)
    if status >= 400:
        raise HTTPException(status_code=status, detail=str(body))
    return body


@router.patch("/projects/{project_id}")
async def _route_update_project(
    project_id: str,
    payload: dict = Body(...),
    authorization: str | None = Header(default=None),
):
    status, body = await _proxy(
        "PATCH",
        f"/api/projects/{project_id}",
        authorization,
        json_body=payload,
    )
    if status >= 400:
        raise HTTPException(status_code=status, detail=str(body))
    return body


@router.delete("/projects/{project_id}", status_code=204)
async def _route_delete_project(
    project_id: str,
    authorization: str | None = Header(default=None),
):
    await _proxy("DELETE", f"/api/projects/{project_id}", authorization)
    return Response(status_code=204)


# Project members — sharing endpoints. AuthZ enforced server-side.


@router.get("/projects/{project_id}/members")
async def _route_list_project_members(
    project_id: str,
    authorization: str | None = Header(default=None),
):
    return await _proxy_get(f"/api/projects/{project_id}/members", authorization)


@router.post("/projects/{project_id}/members", status_code=201)
async def _route_add_project_member(
    project_id: str,
    payload: dict = Body(...),
    authorization: str | None = Header(default=None),
):
    status, body = await _proxy(
        "POST",
        f"/api/projects/{project_id}/members",
        authorization,
        json_body=payload,
    )
    if status >= 400:
        raise HTTPException(status_code=status, detail=str(body))
    return body


@router.patch("/projects/{project_id}/members/{member_user_id}")
async def _route_update_project_member_role(
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
async def _route_remove_project_member(
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
