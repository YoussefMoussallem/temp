"""POST /agent/memories/from-text — UI-driven memory create/edit (Phase 3.5).

End users write memories in plain English; the backend calls an LLM to
structure the input into the persisted schema (slug / type / name /
description / body), then upserts via db-service. The agent's tool-
gated read/save pattern is unchanged — this is a sibling channel
powered by the UI drawer.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

from app.bridges import db_client
from app.dependencies import CurrentUser, get_current_user
from app.middleware.rate_limit import limiter, user_or_ip_key
from app_logger import get_logger

log = get_logger(__name__)

router = APIRouter(tags=["agent"])


class MemoryFromTextRequest(BaseModel):
    scope: Literal["user", "project"]
    text: str
    # Required when scope == "project". Ignored for scope == "user"
    # (the caller's own oid is used instead).
    project_id: str | None = None
    # When present, forces the structured output to use THIS slug —
    # signalling "I'm editing this specific entry". Without it the
    # LLM picks a slug (potentially reusing an existing one if the
    # text supersedes; potentially creating a fresh one if not).
    slug: str | None = None


@router.post("/memories/from-text")
# Each save is one LLM call. 30/min is generous for interactive use
# (a user typing memories) but stops a script that spams the endpoint
# from burning model budget. Same key as /turn so a user's overall
# memory + chat budget stays comparable.
@limiter.limit("30/minute", key_func=user_or_ip_key)
async def memory_from_text(
    request: Request,
    body: MemoryFromTextRequest,
    authorization: str | None = Header(default=None),
    user: CurrentUser = Depends(get_current_user),
):
    """Structure plain text into a memory and upsert it.

    Returns the saved memory (same shape as the GET endpoints), so the
    FE can render it in the list without a separate refetch.
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    if not body.text or not body.text.strip():
        raise HTTPException(status_code=400, detail="text is required")
    if body.scope == "project" and not body.project_id:
        raise HTTPException(
            status_code=400,
            detail="project_id is required for scope=project",
        )

    # Late import — pulls in the LLM provider stack which is heavy at
    # module load time.
    from ..services.memories import structure_memory_text  # noqa: PLC0415

    # Fetch the existing index so the LLM can detect supersession /
    # contradiction and reuse a slug rather than create a sibling.
    if body.scope == "user":
        existing = await db_client.list_user_memories(authorization, user.user_id)
    else:
        existing = await db_client.list_project_memories(
            authorization,
            body.project_id or "",
        )

    try:
        structured = await structure_memory_text(
            authorization=authorization,
            text=body.text,
            scope=body.scope,
            existing_index=existing,
            force_slug=body.slug,
        )
    except ValueError as e:
        # Bad LLM output (non-JSON, missing field, malformed). Surface
        # as 422 so the FE can show a friendly retry prompt.
        raise HTTPException(status_code=422, detail=str(e)) from e

    try:
        if body.scope == "user":
            saved = await db_client.upsert_user_memory(
                authorization,
                user.user_id,
                **structured,
            )
        else:
            saved = await db_client.upsert_project_memory(
                authorization,
                body.project_id or "",
                **structured,
            )
    except Exception as e:  # noqa: BLE001
        log.exception("memory_from_text: upsert failed: %s", e)
        raise HTTPException(status_code=502, detail="Failed to persist memory") from e

    return saved
