"""HTTP client for the DB microservice.

Why this is separate from ``app/db/router.py``
-----------------------------------------------
``app/db/router.py`` is a dumb proxy used by the *frontend*: it takes
the user's bearer token and forwards it verbatim. This module is used
by the *backend itself* (agent tools, usage recording, auth helpers) -
it still accepts the caller's Authorization header, but each function
knows the shape of the DB-service endpoint it hits and returns typed
Python values instead of raw HTTP responses.

Error-handling policy - two tiers
---------------------------------
  * ``record_usage`` / ``get_my_usage`` / ``validate_token`` - swallow
    exceptions and return ``None``. These are best-effort: failing to
    log a billable event or fetch a dashboard page should never break
    a live chat turn.
  * Projects / conversations / messages / slides - ``raise_for_status``
    so HTTP errors propagate. These calls are on the critical path for
    every turn; the agent loop / turn handler knows how to surface them
    to the client.

Every function takes ``authorization`` (the raw
``"Bearer <jwt>"`` header) so the DB service can enforce ownership /
AuthZ. We do not inspect or rewrite the token here.

Client lifecycle
----------------
We open a fresh ``httpx.AsyncClient`` per call (``async with``). That's
slightly wasteful vs. a shared pool, but these calls are infrequent
per turn and the isolation avoids cross-request bleed. If you see
per-call latency climb on a hot path, migrate that specific function
to use a shared client.
"""

from __future__ import annotations

import httpx
from app_logger import get_logger
from app.config import get_settings

log = get_logger(__name__)

# Cached base URL so we only read settings once. Not locked because
# a torn read of a string is harmless (same value every time).
_BASE_URL: str | None = None


def _get_base_url() -> str:
    """Return the db-service base URL, minus any trailing slash."""
    global _BASE_URL
    if _BASE_URL is None:
        _BASE_URL = get_settings().app.db_service_url.rstrip("/")
    return _BASE_URL


async def record_usage(
    *,
    user_id: str,
    email: str,
    display_name: str | None,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
) -> dict | None:
    """Record one billable usage entry via the DB service.

    Best-effort: returns ``None`` on any failure so a logging hiccup
    never bubbles up as a 500 to the end user. The trade-off is that
    usage data may be silently incomplete - watch db-service logs for
    repeated failures.
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{_get_base_url()}/api/usage/record",
                json={
                    "user_id": user_id,
                    "email": email,
                    "display_name": display_name,
                    "model": model,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cost_usd": cost_usd,
                },
            )
            resp.raise_for_status()
            return resp.json()
    except Exception:
        log.warning("Failed to record usage via db-service", exc_info=True)
        return None


async def get_my_usage(authorization: str, start: str | None = None, end: str | None = None) -> dict | None:
    """Get the caller's usage totals + records, optionally date-windowed.

    Returns ``None`` on failure; the caller (``db/router.py::my_usage``)
    converts that into an empty-shape response so the dashboard can
    still render. ``start`` / ``end`` are ISO dates; omit to return
    the full history.
    """
    try:
        params = {}
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{_get_base_url()}/api/usage/me",
                headers={"Authorization": authorization},
                params=params,
            )
            resp.raise_for_status()
            return resp.json()
    except Exception:
        log.warning("Failed to get usage from db-service", exc_info=True)
        return None


async def validate_token(authorization: str) -> dict | None:
    """Ask the DB service to validate a bearer token.

    Returns a user-info dict on success, ``None`` on any failure
    (network, 401, 403, etc.). Callers should treat ``None`` as
    "not authenticated" without inspecting why. Used by components
    that need the DB service's view of the user (e.g. to confirm the
    user row exists) rather than just the JWT claims we validated
    locally in ``app.dependencies``.
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{_get_base_url()}/api/auth/validate",
                headers={"Authorization": authorization},
            )
            resp.raise_for_status()
            return resp.json()
    except Exception:
        return None


# ── Projects / conversations / messages ────────────────────────────────────
#
# Unlike usage/auth (nice-to-have, failures swallowed), these are on the
# critical path for every turn. They raise on HTTP error so the turn handler
# can surface the failure to the client cleanly.
#
# Message writes are append-only: ``append_message`` only adds; edits or
# branching happen by creating new messages, never mutating existing ones.
# The DB service assigns a monotonically increasing ``sequence`` per
# conversation, which is what ``get_messages`` paginates on.


async def list_projects(authorization: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{_get_base_url()}/api/projects",
            headers={"Authorization": authorization},
        )
        resp.raise_for_status()
        return resp.json().get("projects", [])


async def create_project(
    authorization: str, *, name: str, description: str | None = None
) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{_get_base_url()}/api/projects",
            headers={"Authorization": authorization},
            json={"name": name, "description": description},
        )
        resp.raise_for_status()
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
        resp.raise_for_status()
        return resp.json()


async def delete_project(authorization: str, project_id: str) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.delete(
            f"{_get_base_url()}/api/projects/{project_id}",
            headers={"Authorization": authorization},
        )
        resp.raise_for_status()


async def list_conversations(authorization: str, project_id: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{_get_base_url()}/api/projects/{project_id}/conversations",
            headers={"Authorization": authorization},
        )
        resp.raise_for_status()
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
        resp.raise_for_status()
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
        resp.raise_for_status()
        return resp.json()


async def delete_conversation(authorization: str, conversation_id: str) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.delete(
            f"{_get_base_url()}/api/conversations/{conversation_id}",
            headers={"Authorization": authorization},
        )
        resp.raise_for_status()


async def get_conversation(
    authorization: str, conversation_id: str
) -> dict | None:
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
            conversation_id, exc_info=True,
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
            conversation_id, exc_info=True,
        )
        return None


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
        resp.raise_for_status()


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
        resp.raise_for_status()
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
        resp.raise_for_status()
        return resp.json()


# ── Slides ────────────────────────────────────────────────────────────────
#
# Slide tools (in ``app.agent.services.tools``) call these from inside
# their ``call()`` methods. Slides are owned by a project and rendered
# in-chat; mutations are immediate (no draft/commit step). Reordering
# returns the full list so the turn handler can emit one
# ``slides_replaced`` event instead of N individual updates.


async def list_slides(authorization: str, project_id: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{_get_base_url()}/api/projects/{project_id}/slides",
            headers={"Authorization": authorization},
        )
        resp.raise_for_status()
        return resp.json().get("slides", [])


async def create_slide(
    authorization: str,
    project_id: str,
    *,
    html: str,
    title: str | None = None,
    after_slide_id: str | None = None,
) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{_get_base_url()}/api/projects/{project_id}/slides",
            headers={"Authorization": authorization},
            json={
                "html": html,
                "title": title,
                "after_slide_id": after_slide_id,
            },
        )
        resp.raise_for_status()
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
        resp.raise_for_status()
        return resp.json()


async def delete_slide(authorization: str, slide_id: str) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.delete(
            f"{_get_base_url()}/api/slides/{slide_id}",
            headers={"Authorization": authorization},
        )
        resp.raise_for_status()


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
        resp.raise_for_status()
        return resp.json().get("slides", [])
