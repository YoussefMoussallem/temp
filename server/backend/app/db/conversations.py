"""Conversations — list/create/update/delete/get + per-turn token counters.

Mixed-tier client: list/create/update/delete are critical-path (raise
via ``_check_response``); ``get_conversation`` + ``add_conversation_tokens``
are best-effort (failures swallowed, return None) because they're
informational, not load-bearing on the turn.

FE proxy covers list/create/patch/delete (the agent-loop's tokens
endpoint isn't exposed to the FE).
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Body, Header, HTTPException, Response

from ._shared import _check_response, _get_base_url, log
from ._shared_proxy import _proxy, _proxy_get


# ===========================================================================
# Typed client — used by backend code
# ===========================================================================


async def list_conversations(authorization: str, project_id: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{_get_base_url()}/api/projects/{project_id}/conversations",
            headers={"Authorization": authorization},
        )
        _check_response(resp)
        return resp.json().get("conversations", [])


async def create_conversation(
    authorization: str, project_id: str, *, title: str = "Untitled"
) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{_get_base_url()}/api/projects/{project_id}/conversations",
            headers={"Authorization": authorization},
            json={"title": title},
        )
        _check_response(resp)
        return resp.json()


async def update_conversation_title(
    authorization: str, conversation_id: str, *, title: str
) -> dict:
    """PATCH a conversation's title. Used by the auto-title generator
    after a fresh chat receives its first user message; could be reused
    by an explicit rename UI later.
    """
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.patch(
            f"{_get_base_url()}/api/conversations/{conversation_id}",
            headers={"Authorization": authorization},
            json={"title": title},
        )
        _check_response(resp)
        return resp.json()


async def delete_conversation(authorization: str, conversation_id: str) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.delete(
            f"{_get_base_url()}/api/conversations/{conversation_id}",
            headers={"Authorization": authorization},
        )
        _check_response(resp)


async def get_conversation(authorization: str, conversation_id: str) -> dict | None:
    """Fetch a single conversation row including running token counters.

    Best-effort: returns ``None`` on any failure so /context can fall
    back to the chars/4 approximation if the row can't be fetched.
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{_get_base_url()}/api/conversations/{conversation_id}",
                headers={"Authorization": authorization},
            )
            resp.raise_for_status()
            return resp.json()
    except Exception:
        log.warning(
            "Failed to fetch conversation %s from db-service",
            conversation_id,
            exc_info=True,
        )
        return None


async def add_conversation_tokens(
    authorization: str,
    conversation_id: str,
    *,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float = 0.0,
) -> dict | None:
    """Add per-turn input/output/cost deltas to a conversation's totals.

    Best-effort: a failure here must never fail the turn — token tracking
    is informational. Negative deltas are rejected by db-service (and
    short-circuited here so we don't even hit the network).

    ``cost_usd`` is computed by the caller via ``litellm_bridge.
    calculate_cost`` for the same model + token deltas being recorded
    here. Defaulting to 0 keeps callers that don't yet pass cost
    backwards-compatible — the cost column simply doesn't move.
    """
    if input_tokens <= 0 and output_tokens <= 0 and cost_usd <= 0:
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{_get_base_url()}/api/conversations/{conversation_id}/tokens",
                headers={"Authorization": authorization},
                json={
                    "input_tokens": max(0, input_tokens),
                    "output_tokens": max(0, output_tokens),
                    "cost_usd": max(0.0, float(cost_usd)),
                },
            )
            resp.raise_for_status()
            return resp.json()
    except Exception:
        log.warning(
            "Failed to bump conversation tokens for %s",
            conversation_id,
            exc_info=True,
        )
        return None


# ===========================================================================
# FastAPI router — FE proxy
# ===========================================================================

router = APIRouter(tags=["db"])


@router.get("/projects/{project_id}/conversations")
async def _route_list_conversations(
    project_id: str,
    authorization: str | None = Header(default=None),
):
    return await _proxy_get(f"/api/projects/{project_id}/conversations", authorization)


@router.post("/projects/{project_id}/conversations")
async def _route_create_conversation(
    project_id: str,
    payload: dict = Body(...),
    authorization: str | None = Header(default=None),
):
    status, body = await _proxy(
        "POST",
        f"/api/projects/{project_id}/conversations",
        authorization,
        json_body=payload,
    )
    if status >= 400:
        raise HTTPException(status_code=status, detail=str(body))
    return body


@router.patch("/conversations/{conversation_id}")
async def _route_update_conversation(
    conversation_id: str,
    payload: dict = Body(...),
    authorization: str | None = Header(default=None),
):
    """Rename a conversation. Body: ``{title: str}``. Forwards directly
    to db-service which enforces editor role + length validation.
    """
    status, body = await _proxy(
        "PATCH",
        f"/api/conversations/{conversation_id}",
        authorization,
        json_body=payload,
    )
    if status >= 400:
        raise HTTPException(status_code=status, detail=str(body))
    return body


@router.delete("/conversations/{conversation_id}", status_code=204)
async def _route_delete_conversation(
    conversation_id: str,
    authorization: str | None = Header(default=None),
):
    await _proxy("DELETE", f"/api/conversations/{conversation_id}", authorization)
    return Response(status_code=204)
