"""Slide CRUD endpoints — project-scoped deck, latest-only.

Access goes through ``require_project_access`` on the slide's parent
project:

| Operation                                 | Min role |
|-------------------------------------------|----------|
| GET    /projects/{id}/slides              | viewer   |
| POST   /projects/{id}/slides              | editor   |
| PATCH  /slides/{slide_id}                 | editor   |
| DELETE /slides/{slide_id}                 | editor   |
| POST   /slides/{slide_id}/reorder         | editor   |

Endpoints split across two prefixes:
- ``/projects/{project_id}/slides`` — list + create (project-scoped)
- ``/slides/{slide_id}`` — patch / delete / reorder (slide-scoped)
"""

from __future__ import annotations

from dataclasses import asdict
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.db import Pool, cache_del, cache_get_json, cache_set_json, get_pool
from app.db.projects.access import require_project_access
from app.db.slides.repository import (
    create_slide,
    delete_slide,
    get_slide,
    list_slides_by_project,
    reorder_slide,
    update_slide,
)
from app.dependencies import CurrentUser, get_current_user

router = APIRouter(tags=["slides"])


def _slides_cache_key(project_id: UUID) -> str:
    return f"cache:project:{project_id}:slides"


class CreateSlideRequest(BaseModel):
    html: str
    title: str | None = None
    after_slide_id: UUID | None = None


class UpdateSlideRequest(BaseModel):
    html: str | None = None
    title: str | None = None


class ReorderSlideRequest(BaseModel):
    after_slide_id: UUID | None = None


def _serialize(slide) -> dict:
    d = asdict(slide)
    for k, v in d.items():
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
        elif isinstance(v, UUID):
            d[k] = str(v)
    return d


async def _require_slide_access(
    pool: Pool, slide_id: UUID, user: CurrentUser, *, min_role: str
):
    """Resolve a slide → its project → role-check the caller.

    Raises 404 if the slide is missing or the caller has no membership;
    403 if their role is below ``min_role``.
    """
    slide = await get_slide(pool, slide_id)
    if slide is None:
        raise HTTPException(status_code=404, detail="Slide not found")
    await require_project_access(pool, slide.project_id, user, min_role=min_role)
    return slide


@router.get("/projects/{project_id}/slides")
async def list_slides(
    project_id: UUID,
    user: CurrentUser = Depends(get_current_user),
):
    pool: Pool = await get_pool()
    await require_project_access(pool, project_id, user, min_role="viewer")

    key = _slides_cache_key(project_id)
    cached = await cache_get_json(key)
    if cached is not None:
        return {"slides": cached}

    slides = await list_slides_by_project(pool, project_id)
    payload = [_serialize(s) for s in slides]
    cache_set_json(key, payload)
    return {"slides": payload}


@router.post("/projects/{project_id}/slides")
async def create(
    project_id: UUID,
    body: CreateSlideRequest,
    user: CurrentUser = Depends(get_current_user),
):
    pool: Pool = await get_pool()
    await require_project_access(pool, project_id, user, min_role="editor")
    try:
        slide = await create_slide(
            pool,
            project_id=project_id,
            html=body.html,
            title=body.title,
            after_slide_id=body.after_slide_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    cache_del(_slides_cache_key(project_id))
    return _serialize(slide)


@router.patch("/slides/{slide_id}")
async def patch(
    slide_id: UUID,
    body: UpdateSlideRequest,
    user: CurrentUser = Depends(get_current_user),
):
    if body.html is None and body.title is None:
        raise HTTPException(status_code=400, detail="Nothing to update")
    pool: Pool = await get_pool()
    slide = await _require_slide_access(pool, slide_id, user, min_role="editor")
    updated = await update_slide(pool, slide_id, html=body.html, title=body.title)
    cache_del(_slides_cache_key(slide.project_id))
    return _serialize(updated)


@router.delete("/slides/{slide_id}", status_code=204)
async def delete(
    slide_id: UUID,
    user: CurrentUser = Depends(get_current_user),
):
    pool: Pool = await get_pool()
    slide = await _require_slide_access(pool, slide_id, user, min_role="editor")
    await delete_slide(pool, slide_id)
    cache_del(_slides_cache_key(slide.project_id))
    return None


@router.post("/slides/{slide_id}/reorder")
async def reorder(
    slide_id: UUID,
    body: ReorderSlideRequest,
    user: CurrentUser = Depends(get_current_user),
):
    pool: Pool = await get_pool()
    slide = await _require_slide_access(pool, slide_id, user, min_role="editor")
    try:
        slides = await reorder_slide(
            pool, slide_id, after_slide_id=body.after_slide_id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    cache_del(_slides_cache_key(slide.project_id))
    return {"slides": [_serialize(s) for s in slides]}
