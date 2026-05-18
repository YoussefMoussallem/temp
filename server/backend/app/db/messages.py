"""Messages — clear / page / append. Append-only:
``append_message`` only adds; edits or branching happen by creating new
messages, never mutating existing ones. The DB service assigns a
monotonically increasing ``sequence`` per conversation, which is what
``get_messages`` paginates on.
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Header, Query

from ._shared import _check_response, _get_base_url
from ._shared_proxy import _proxy_get


# ===========================================================================
# Typed client — used by backend code (/clear command, /compact command, /turn)
# ===========================================================================


async def clear_messages(authorization: str, conversation_id: str) -> None:
    """Truncate every message in a conversation; reset bookkeeping + cache.

    Critical-path on the /clear command: raises on HTTP error so the
    command surfaces the failure to the user instead of silently
    pretending it worked.
    """
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.delete(
            f"{_get_base_url()}/api/conversations/{conversation_id}/messages",
            headers={"Authorization": authorization},
        )
        _check_response(resp)


async def get_messages(
    authorization: str,
    conversation_id: str,
    *,
    before_sequence: int | None = None,
    limit: int = 50,
) -> list[dict]:
    """Fetch a page of messages, newest-first, for a conversation.

    Keyset pagination on ``sequence``: pass the lowest sequence you
    already have as ``before_sequence`` to get the next older page.
    """
    params: dict = {"limit": limit}
    if before_sequence is not None:
        params["before_sequence"] = before_sequence
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{_get_base_url()}/api/conversations/{conversation_id}/messages",
            headers={"Authorization": authorization},
            params=params,
        )
        _check_response(resp)
        return resp.json().get("messages", [])


async def append_message(
    authorization: str,
    conversation_id: str,
    *,
    role: str,
    content: list[dict],
) -> dict:
    """Append a message (user / assistant / tool) to a conversation.

    ``content`` is the multi-part block list (text + tool calls + tool
    results), matching the LLM provider's message schema. The DB
    service is the authority on ``sequence`` - we don't pass one.
    """
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{_get_base_url()}/api/conversations/{conversation_id}/messages",
            headers={"Authorization": authorization},
            json={"role": role, "content": content},
        )
        _check_response(resp)
        return resp.json()


# ===========================================================================
# FastAPI router — FE proxy
# ===========================================================================

router = APIRouter(tags=["db"])


@router.get("/conversations/{conversation_id}/messages")
async def _route_list_messages(
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
        f"/api/conversations/{conversation_id}/messages",
        authorization,
        params,
    )
