"""Slides — typed client (used by slide tools) + FE HTTP proxy.

Slides are owned by a project and rendered in-chat; mutations are
immediate (no draft/commit step). Reordering and delete return the
full list so the turn handler can emit one ``slides_replaced`` event
instead of N individual updates.
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Body, Header, HTTPException, Response

from ._shared import _check_response, _get_base_url
from ._shared_proxy import _proxy, _proxy_get


# ===========================================================================
# Typed client — used by slide tools (CreateSlide / UpdateSlide / etc)
# ===========================================================================


async def list_slides(authorization: str, project_id: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{_get_base_url()}/api/projects/{project_id}/slides",
            headers={"Authorization": authorization},
        )
        _check_response(resp)
        return resp.json().get("slides", [])


async def get_slide(authorization: str, slide_id: str) -> dict | None:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{_get_base_url()}/api/slides/{slide_id}",
            headers={"Authorization": authorization},
        )
        # Soft-404: the agent tool wants "no such row" to surface as
        # ``None`` rather than an is_error tool_result, so it can pick
        # a different slide_id and try again on its own. Other 4xx
        # still go through ``_check_response`` for the detail-extracted
        # ValueError path.
        if resp.status_code == 404:
            return None
        _check_response(resp)
        return resp.json()


async def create_slide(
    authorization: str,
    project_id: str,
    *,
    html: str,
    title: str | None = None,
    after_slide_id: str | None = None,
    position: int | None = None,
) -> dict:
    """Create one slide. Pass either `position` (explicit, no shift,
    parallel-safe) OR `after_slide_id` (relative, transactional shift,
    serial). The db-service rejects 400 if both are set, or if the
    chosen `position` collides with an existing slide in the project
    (the deferrable unique constraint catches the race).

    4xx surfaces through ``_check_response`` as a ValueError carrying
    the db-service detail (e.g. "position N is already taken in this
    project. Pick another position…"), which the agent loop then
    presents to the model as an is_error tool_result so it can retry
    against the next free slot."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{_get_base_url()}/api/projects/{project_id}/slides",
            headers={"Authorization": authorization},
            json={
                "html": html,
                "title": title,
                "after_slide_id": after_slide_id,
                "position": position,
            },
        )
        _check_response(resp)
        return resp.json()


async def update_slide(
    authorization: str,
    slide_id: str,
    *,
    html: str | None = None,
    title: str | None = None,
) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.patch(
            f"{_get_base_url()}/api/slides/{slide_id}",
            headers={"Authorization": authorization},
            json={"html": html, "title": title},
        )
        _check_response(resp)
        return resp.json()


async def delete_slide(authorization: str, slide_id: str) -> list[dict]:
    """Delete a slide and return the project's post-renumber slide list.

    db-service renumbers positions after the delete so the slides stay
    0..N-1 contiguous; the response carries the full ordered list so
    the caller can emit a single ``slides_replaced`` event analogous
    to reorder, instead of a bare ``slide_deleted`` that would leave
    the FE's position fields stale.
    """
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.delete(
            f"{_get_base_url()}/api/slides/{slide_id}",
            headers={"Authorization": authorization},
        )
        _check_response(resp)
        return resp.json().get("slides", [])


async def reorder_slide(
    authorization: str,
    slide_id: str,
    *,
    after_slide_id: str | None = None,
) -> list[dict]:
    """Move a slide; returns the full ordered list so callers can emit
    a single `slides_replaced` event."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{_get_base_url()}/api/slides/{slide_id}/reorder",
            headers={"Authorization": authorization},
            json={"after_slide_id": after_slide_id},
        )
        _check_response(resp)
        return resp.json().get("slides", [])


# ===========================================================================
# FastAPI router — FE proxy
# ===========================================================================
# Slide tools also hit these via the backend's own typed client above, so
# forwarding them through the proxy keeps the slide HTTP contract
# observable from the browser side too.

router = APIRouter(tags=["db"])


@router.get("/projects/{project_id}/slides")
async def _route_list_slides(
    project_id: str,
    authorization: str | None = Header(default=None),
):
    return await _proxy_get(f"/api/projects/{project_id}/slides", authorization)


@router.post("/projects/{project_id}/slides")
async def _route_create_slide(
    project_id: str,
    payload: dict = Body(...),
    authorization: str | None = Header(default=None),
):
    status, body = await _proxy(
        "POST",
        f"/api/projects/{project_id}/slides",
        authorization,
        json_body=payload,
    )
    if status >= 400:
        raise HTTPException(status_code=status, detail=str(body))
    return body


@router.patch("/slides/{slide_id}")
async def _route_update_slide(
    slide_id: str,
    payload: dict = Body(...),
    authorization: str | None = Header(default=None),
):
    status, body = await _proxy(
        "PATCH",
        f"/api/slides/{slide_id}",
        authorization,
        json_body=payload,
    )
    if status >= 400:
        raise HTTPException(status_code=status, detail=str(body))
    return body


@router.delete("/slides/{slide_id}", status_code=204)
async def _route_delete_slide(
    slide_id: str,
    authorization: str | None = Header(default=None),
):
    await _proxy("DELETE", f"/api/slides/{slide_id}", authorization)
    return Response(status_code=204)


@router.post("/slides/{slide_id}/reorder")
async def _route_reorder_slide(
    slide_id: str,
    payload: dict = Body(...),
    authorization: str | None = Header(default=None),
):
    status, body = await _proxy(
        "POST",
        f"/api/slides/{slide_id}/reorder",
        authorization,
        json_body=payload,
    )
    if status >= 400:
        raise HTTPException(status_code=status, detail=str(body))
    return body
