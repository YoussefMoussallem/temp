"""Conversation message endpoints — append-only history + paginated reads.

Access goes through ``require_project_access`` on the conversation's
parent project:

| Operation                                 | Min role |
|-------------------------------------------|----------|
| GET    /conversations/{id}/messages       | viewer   |
| POST   /conversations/{id}/messages       | editor   |
| DELETE /conversations/{id}/messages       | editor   |
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.db import Pool, cache_del, cache_get_json, cache_set_json, get_pool
from app.db.conversations.repository import get_conversation, reset_after_clear
from app.db.messages.repository import append_message, delete_all_messages, list_messages
from app.db.projects.access import require_project_access
from app.dependencies import CurrentUser, get_current_user

router = APIRouter(prefix="/conversations/{conversation_id}/messages", tags=["messages"])


def _messages_cache_key(conversation_id: UUID) -> str:
    return f"cache:conv:{conversation_id}:messages"


def _conv_list_cache_key(project_id: UUID) -> str:
    return f"cache:project:{project_id}:conv_list"


class AppendMessageRequest(BaseModel):
    role: str
    content: list[dict[str, Any]]


def _serialize(message) -> dict:
    d = asdict(message)
    for k, v in d.items():
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
        elif isinstance(v, UUID):
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
    await require_project_access(
        pool, conversation.project_id, user, min_role=min_role
    )
    return conversation


@router.get("")
async def get_messages(
    conversation_id: UUID,
    before_sequence: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    user: CurrentUser = Depends(get_current_user),
):
    pool: Pool = await get_pool()
    await _require_conversation_access(
        pool, conversation_id, user, min_role="viewer"
    )

    # Only cache full-history reads; paginated reads are rare and small enough.
    if before_sequence is None:
        key = _messages_cache_key(conversation_id)
        cached = await cache_get_json(key)
        if cached is not None:
            return {"messages": cached}
        messages = await list_messages(pool, conversation_id)
        payload = [_serialize(m) for m in messages]
        cache_set_json(key, payload)
        return {"messages": payload}

    messages = await list_messages(
        pool, conversation_id, before_sequence=before_sequence, limit=limit
    )
    return {"messages": [_serialize(m) for m in messages]}


@router.post("")
async def append(
    conversation_id: UUID,
    body: AppendMessageRequest,
    user: CurrentUser = Depends(get_current_user),
):
    if body.role not in ("user", "assistant", "system"):
        raise HTTPException(status_code=400, detail="Invalid role")
    pool: Pool = await get_pool()
    conversation = await _require_conversation_access(
        pool, conversation_id, user, min_role="editor"
    )

    message = await append_message(
        pool,
        conversation_id=conversation_id,
        role=body.role,
        content=body.content,
    )
    # Invalidate: this conversation's history, and its parent project's
    # conversation list (because last_active_at changed and list order depends on it).
    cache_del(
        _messages_cache_key(conversation_id),
        _conv_list_cache_key(conversation.project_id),
    )
    return _serialize(message)


@router.delete("", status_code=204)
async def delete_all(
    conversation_id: UUID,
    user: CurrentUser = Depends(get_current_user),
):
    """Truncate every message in this conversation, reset bookkeeping, and
    invalidate caches.

    Used by the backend's ``/clear`` slash command. Conversation row stays;
    only its messages and the running token counters reset to zero.
    """
    pool: Pool = await get_pool()
    conversation = await _require_conversation_access(
        pool, conversation_id, user, min_role="editor"
    )

    async with pool.acquire() as conn:
        async with conn.transaction():
            await delete_all_messages(conn, conversation_id)
            await reset_after_clear(conn, conversation_id)

    cache_del(
        _messages_cache_key(conversation_id),
        _conv_list_cache_key(conversation.project_id),
    )
    return None
