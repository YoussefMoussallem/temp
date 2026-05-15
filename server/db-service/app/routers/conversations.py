"""Conversation CRUD endpoints.

Access is delegated to ``require_project_access`` (in
``app/db/projects/access.py``) — every operation needs a role on the
parent project:

| Operation                                 | Min role |
|-------------------------------------------|----------|
| GET    /projects/{id}/conversations       | viewer   |
| POST   /projects/{id}/conversations       | editor   |
| GET    /conversations/{id}                | viewer   |
| PATCH  /conversations/{id}                | editor   |
| POST   /conversations/{id}/tokens         | editor   |
| DELETE /conversations/{id}                | editor   |

For conversation-scoped endpoints we first look up the conversation (to
find its ``project_id``), then check the role on that project. Returns
404 if the conversation doesn't exist OR the caller has no membership
on its project, so we never leak existence to non-members.
"""

from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.db import Pool, cache_del, cache_get_json, cache_set_json, get_pool
from app.db.conversations.repository import (
    add_tokens,
    create_conversation,
    delete_conversation,
    get_conversation,
    list_conversations_by_project,
    update_title,
)
from app.db.projects.access import require_project_access
from app.dependencies import CurrentUser, get_current_user

router = APIRouter(tags=["conversations"])


def _conv_list_cache_key(project_id: UUID) -> str:
    return f"cache:project:{project_id}:conv_list"


class CreateConversationRequest(BaseModel):
    title: str = "Untitled"


class UpdateConversationRequest(BaseModel):
    """Body of PATCH /conversations/{id}. Only ``title`` is patchable
    today. Other rename-able fields would land here as additional optional
    fields; the router applies whatever's set and ignores ``None``s.
    """

    title: str | None = None


class AddTokensRequest(BaseModel):
    """Body of POST /conversations/{id}/tokens.

    All fields are deltas (added to running totals); negative values are
    rejected at the router so a buggy caller can't silently zero out a
    user's history. ``cost_usd`` is optional — callers that don't yet
    compute cost can omit it and the cost column stays unchanged.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


def _serialize(conversation) -> dict:
    d = asdict(conversation)
    for k, v in d.items():
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
        elif isinstance(v, UUID):
            d[k] = str(v)
        elif isinstance(v, Decimal):
            # JSON has no native Decimal; stringifying preserves precision
            # for cost values that the frontend then ``Number()``s.
            d[k] = str(v)
    return d


async def _require_conversation_access(
    pool: Pool, conversation_id: UUID, user: CurrentUser, *, min_role: str
):
    """Resolve a conversation → its project → role-check the caller.

    Raises 404 if the conversation is missing or the caller has no
    membership; 403 if their role is below ``min_role``.
    """
    conversation = await get_conversation(pool, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    await require_project_access(pool, conversation.project_id, user, min_role=min_role)
    return conversation


@router.get("/projects/{project_id}/conversations")
async def list_conversations(
    project_id: UUID,
    user: CurrentUser = Depends(get_current_user),
):
    pool: Pool = await get_pool()
    await require_project_access(pool, project_id, user, min_role="viewer")

    key = _conv_list_cache_key(project_id)
    cached = await cache_get_json(key)
    if cached is not None:
        return {"conversations": cached}

    conversations = await list_conversations_by_project(pool, project_id)
    payload = [_serialize(c) for c in conversations]
    cache_set_json(key, payload)
    return {"conversations": payload}


@router.post("/projects/{project_id}/conversations")
async def create(
    project_id: UUID,
    body: CreateConversationRequest,
    user: CurrentUser = Depends(get_current_user),
):
    pool: Pool = await get_pool()
    await require_project_access(pool, project_id, user, min_role="editor")
    conversation = await create_conversation(pool, project_id=project_id, title=body.title)
    cache_del(_conv_list_cache_key(project_id))
    return _serialize(conversation)


@router.get("/conversations/{conversation_id}")
async def get_one(
    conversation_id: UUID,
    user: CurrentUser = Depends(get_current_user),
):
    """Return a single conversation row, including running token counters.

    Used by the backend's ``/context`` command to show real input footprint
    instead of approximating from message content.
    """
    pool: Pool = await get_pool()
    conversation = await _require_conversation_access(
        pool, conversation_id, user, min_role="viewer"
    )
    return _serialize(conversation)


@router.patch("/conversations/{conversation_id}")
async def patch(
    conversation_id: UUID,
    body: UpdateConversationRequest,
    user: CurrentUser = Depends(get_current_user),
):
    """Rename a conversation. Editor role on the parent project required.

    Only ``title`` is patchable. ``None`` is treated as "leave as-is";
    an empty-after-strip ``title`` is rejected as 400 (a blank title is
    indistinguishable from "Untitled" in the sidebar but breaks the
    audit trail of auto-titled chats).
    """
    pool: Pool = await get_pool()
    conversation = await _require_conversation_access(
        pool, conversation_id, user, min_role="editor"
    )

    if body.title is None:
        # Nothing to do — but still return current state so the FE can
        # treat PATCH as idempotent.
        return _serialize(conversation)

    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="title must not be blank")
    # Soft cap to keep the sidebar laid out predictably. The DB has no
    # explicit length constraint today; this is a UX guardrail, not a
    # data-integrity one.
    if len(title) > 200:
        title = title[:200].rstrip()

    updated = await update_title(pool, conversation_id, title=title)
    if updated is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    cache_del(_conv_list_cache_key(conversation.project_id))
    return _serialize(updated)


@router.post("/conversations/{conversation_id}/tokens")
async def add_conversation_tokens(
    conversation_id: UUID,
    body: AddTokensRequest,
    user: CurrentUser = Depends(get_current_user),
):
    """Add per-turn token deltas to a conversation's running totals.

    Called by the backend after each /turn finishes so ``/context`` can
    show actual input footprint. Best-effort on the caller side: a
    failure here doesn't fail the turn.
    """
    if body.input_tokens < 0 or body.output_tokens < 0 or body.cost_usd < 0:
        raise HTTPException(status_code=400, detail="Deltas must be non-negative")
    pool: Pool = await get_pool()
    conversation = await _require_conversation_access(
        pool, conversation_id, user, min_role="editor"
    )
    updated = await add_tokens(
        pool,
        conversation_id,
        input_tokens=body.input_tokens,
        output_tokens=body.output_tokens,
        cost_usd=body.cost_usd,
    )
    if updated is None:
        # Row vanished between the access check and the update.
        raise HTTPException(status_code=404, detail="Conversation not found")
    cache_del(_conv_list_cache_key(conversation.project_id))
    return _serialize(updated)


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete(
    conversation_id: UUID,
    user: CurrentUser = Depends(get_current_user),
):
    pool: Pool = await get_pool()
    conversation = await _require_conversation_access(
        pool, conversation_id, user, min_role="editor"
    )
    await delete_conversation(pool, conversation_id)
    cache_del(_conv_list_cache_key(conversation.project_id))
    return None
