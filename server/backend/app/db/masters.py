"""Masters — project-scoped deck templates.

All five HTTP methods in the typed client go through the same
critical-path policy as projects/slides: ``raise_for_status`` so
failures surface to the agent loop. Best-effort would silently break
a deck Generate-Slide turn. ``get_active_master_for_project`` is the
one best-effort exception because it's called on every /turn entry.

FE proxy is read-only by design — bytes-bearing creates go through
``/api/agent/masters/upload`` (multipart) so we don't shuffle 50 MB
of base64 through this dumb proxy. The router also exposes layout
curation endpoints used by the masters detail page.
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Body, Header, HTTPException, Response
from typing import Any

from ._shared import _get_base_url, log
from ._shared_proxy import _proxy, _proxy_get


# ===========================================================================
# Typed client — used by /api/agent/masters/upload + active-master lookup
# ===========================================================================


async def list_masters(authorization: str, project_id: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{_get_base_url()}/api/projects/{project_id}/masters",
            headers={"Authorization": authorization},
        )
        resp.raise_for_status()
        return resp.json().get("masters", [])


async def get_active_master_for_project(
    authorization: str,
    project_id: str,
) -> dict | None:
    """Return ``{master, layouts}`` for the project's active master, or
    ``None`` when no master is active.

    Two HTTP hops on the agent's hot path (turn entry), so this is
    best-effort: any failure returns ``None`` and the QueryEngine
    appendix falls through to "no active master" rather than failing
    the turn. The list-masters call is the cache-warm one — it's
    already hit by the FE on the masters page — so the layouts call
    is the only true cold read.
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{_get_base_url()}/api/projects/{project_id}/masters",
                headers={"Authorization": authorization},
            )
            resp.raise_for_status()
            body = resp.json()
            active_id = body.get("active_master_id")
            if not active_id:
                return None
            master = next(
                (m for m in body.get("masters", []) if m.get("id") == active_id),
                None,
            )
            if master is None:
                return None

            layouts_resp = await client.get(
                f"{_get_base_url()}/api/masters/{active_id}/layouts",
                headers={"Authorization": authorization},
            )
            layouts_resp.raise_for_status()
            layouts = layouts_resp.json().get("layouts", [])
            return {"master": master, "layouts": layouts}
    except Exception:
        log.warning(
            "Failed to fetch active master for project %s",
            project_id,
            exc_info=True,
        )
        return None


async def create_master(
    authorization: str,
    project_id: str,
    *,
    name: str,
    manifest: dict,
    source_sha256: str | None = None,
    source_pptx_b64: str | None = None,
    layouts: list[dict] | None = None,
    fonts: list[dict] | None = None,
) -> dict:
    """Persist a master row, optionally with .pptx bytes (b64),
    per-layout rows, and bundled brand fonts.

    db-service uploads the bytes to blob and stores the URL on the row.
    When ``layouts`` is provided, db-service also writes one master_layouts
    row per entry and (if preview_b64 is set on a layout) uploads each
    PNG preview to blob. When ``fonts`` is provided, each font is
    uploaded under ``{project_id}/{sha}/fonts/{filename}`` and the
    metadata persists on ``masters.fonts_assets``. Timeout is generous
    because heavily-illustrated templates can be 50+ MB and the
    round-trip includes the b64 encode + db-service blob upload.
    """
    body: dict = {
        "name": name,
        "manifest": manifest,
        "source_sha256": source_sha256,
        "source_pptx_b64": source_pptx_b64,
    }
    if layouts is not None:
        body["layouts"] = layouts
    if fonts is not None:
        body["fonts"] = fonts
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{_get_base_url()}/api/projects/{project_id}/masters",
            headers={"Authorization": authorization},
            json=body,
        )
        resp.raise_for_status()
        return resp.json()


async def get_master(authorization: str, master_id: str) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{_get_base_url()}/api/masters/{master_id}",
            headers={"Authorization": authorization},
        )
        resp.raise_for_status()
        return resp.json()


async def get_master_pptx(authorization: str, master_id: str) -> bytes:
    """Fetch the original .pptx for export-time master inheritance."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{_get_base_url()}/api/masters/{master_id}/pptx",
            headers={"Authorization": authorization},
        )
        resp.raise_for_status()
        return resp.content


async def activate_master(authorization: str, master_id: str) -> dict:
    """Set ``projects.active_master_id`` to this master.

    Returns ``{"project_id": ..., "active_master_id": ...}`` so the
    caller can update local state without a follow-up GET.
    """
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{_get_base_url()}/api/masters/{master_id}/activate",
            headers={"Authorization": authorization},
        )
        resp.raise_for_status()
        return resp.json()


async def delete_master(authorization: str, master_id: str) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.delete(
            f"{_get_base_url()}/api/masters/{master_id}",
            headers={"Authorization": authorization},
        )
        resp.raise_for_status()


# ===========================================================================
# FastAPI router — FE proxy
# ===========================================================================

router = APIRouter(tags=["db"])


@router.get("/projects/{project_id}/masters")
async def _route_list_masters(
    project_id: str,
    authorization: str | None = Header(default=None),
):
    return await _proxy_get(f"/api/projects/{project_id}/masters", authorization)


@router.get("/masters/{master_id}")
async def _route_get_master(
    master_id: str,
    authorization: str | None = Header(default=None),
):
    return await _proxy_get(f"/api/masters/{master_id}", authorization)


@router.get("/masters/{master_id}/pptx")
async def _route_get_master_pptx(
    master_id: str,
    authorization: str | None = Header(default=None),
):
    """Stream the original .pptx — bytes path. ``_proxy_get`` returns
    JSON; we need raw bytes here, so go through httpx directly.
    """
    import httpx as _httpx  # noqa: PLC0415 — defer import on this rarely-hit path

    from app.config import get_settings  # noqa: PLC0415

    base = get_settings().app.db_service_url.rstrip("/")
    async with _httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{base}/api/masters/{master_id}/pptx",
            headers={"Authorization": authorization} if authorization else {},
        )
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return Response(
        content=resp.content,
        media_type=("application/vnd.openxmlformats-officedocument.presentationml.presentation"),
    )


@router.post("/masters/{master_id}/activate")
async def _route_activate_master(
    master_id: str,
    authorization: str | None = Header(default=None),
):
    status, body = await _proxy(
        "POST",
        f"/api/masters/{master_id}/activate",
        authorization,
    )
    if status >= 400:
        raise HTTPException(status_code=status, detail=str(body))
    return body


@router.delete("/masters/{master_id}", status_code=204)
async def _route_delete_master(
    master_id: str,
    authorization: str | None = Header(default=None),
):
    await _proxy("DELETE", f"/api/masters/{master_id}", authorization)
    return Response(status_code=204)


# Master layouts — curation UI. GET listing + per-row PATCH/default
# endpoints. The detail page reads the listing once and dispatches
# PATCHes per cell edit; we don't proxy bulk-update because each
# curation change is independently meaningful (and rate limits stay
# aligned with how a human edits).


@router.get("/masters/{master_id}/layouts")
async def _route_list_master_layouts(
    master_id: str,
    authorization: str | None = Header(default=None),
):
    return await _proxy_get(f"/api/masters/{master_id}/layouts", authorization)


@router.patch("/master_layouts/{layout_id}")
async def _route_patch_master_layout(
    layout_id: str,
    payload: dict[str, Any],
    authorization: str | None = Header(default=None),
):
    status, body = await _proxy(
        "PATCH",
        f"/api/master_layouts/{layout_id}",
        authorization,
        json_body=payload,
    )
    if status >= 400:
        raise HTTPException(status_code=status, detail=str(body))
    return body


@router.post("/master_layouts/{layout_id}/default")
async def _route_post_master_layout_default(
    layout_id: str,
    authorization: str | None = Header(default=None),
):
    status, body = await _proxy(
        "POST",
        f"/api/master_layouts/{layout_id}/default",
        authorization,
    )
    if status >= 400:
        raise HTTPException(status_code=status, detail=str(body))
    return body
