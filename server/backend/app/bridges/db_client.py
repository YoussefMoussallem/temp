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
  * ``record_usage`` / ``get_my_usage`` / ``validate_token`` /
    ``get_conversation`` / ``add_conversation_tokens`` - swallow
    exceptions and return ``None``. These are best-effort: failing to
    log a billable event or fetch a dashboard page should never break
    a live chat turn.
  * Critical-path (projects / conversations / messages / slides /
    memories) - route every response through ``_check_response`` so
    HTTP errors surface to the caller. For 4xx with a parseable
    ``{"detail": "..."}`` body, that becomes a clean
    ``ValueError(detail)`` — the agent loop's
    ``_execute_single_tool`` then wraps it as
    ``"Tool execution failed: {detail}"`` in an is_error tool_result,
    so the model sees the actionable hint (e.g. "position 3 is
    already taken in this project. Pick another position…") rather
    than the opaque "Client error '400 Bad Request' for url '…'"
    that ``httpx.HTTPStatusError.__str__`` produces by default.
    5xx is still routed through ``raise_for_status()`` (server bug,
    not the agent's job to fix).

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


# ── Error surfacing ───────────────────────────────────────────────────────


def _check_response(resp: httpx.Response) -> None:
    """Raise a clean ``ValueError(detail)`` for 4xx responses that
    carry a db-service ``{"detail": "..."}`` body; defer to
    ``resp.raise_for_status()`` for 5xx and for 4xx without a
    parseable detail.

    **Why this exists.** The agent loop wraps any exception from a
    tool's ``call()`` into an is_error tool_result whose body is
    ``f"Tool execution failed: {e}"``. If we let
    ``resp.raise_for_status()`` surface ``httpx.HTTPStatusError``, the
    agent sees ``"Client error '400 Bad Request' for url '…'"`` and
    has no idea what to fix. Extracting ``detail`` first means the
    agent sees whatever actionable text the db-service router put in
    the response body (e.g. ``"position 3 is already taken in this
    project. Pick another position…"``, ``"slide not found"``,
    ``"Provide either `position` or `after_slide_id`, not both."``).

    **Scope.** Used by every critical-path bridge below. The
    best-effort tier (``record_usage`` / ``get_my_usage`` /
    ``validate_token`` / ``get_conversation`` /
    ``add_conversation_tokens``) intentionally wraps the whole call in
    ``try: … except Exception: log + return None``, so it doesn't
    need / want the extra translation step.

    **5xx note.** Left to ``raise_for_status()`` because the agent
    shouldn't try to "fix" a server bug — the default exception path
    surfaces the failure to the turn handler as-is.

    **404 callers.** Several ``get_*`` bridges treat 404 as "no such
    row, return None" rather than an error. Those still check
    ``resp.status_code == 404`` explicitly *before* calling this
    helper; the soft-404 isn't a property we should bake in here
    because some endpoints (e.g. ``delete_*``) legitimately mean
    "the thing you're deleting must exist" and a 404 there really is
    an actionable error.
    """
    if 400 <= resp.status_code < 500:
        detail: object = None
        try:
            detail = resp.json().get("detail")
        except Exception:
            detail = None
        if detail:
            # FastAPI 422 (Pydantic validation) emits detail as a list
            # of {loc, msg, type} dicts. Collapse to a readable string
            # so the agent sees one line per validation error rather
            # than a stringified list of dicts.
            if isinstance(detail, list):
                parts: list[str] = []
                for item in detail:
                    if isinstance(item, dict):
                        loc = ".".join(str(x) for x in item.get("loc", []) if x != "body")
                        msg = item.get("msg", "")
                        parts.append(f"{loc}: {msg}" if loc else msg)
                    else:
                        parts.append(str(item))
                detail = "; ".join(p for p in parts if p) or str(detail)
            raise ValueError(str(detail))
    resp.raise_for_status()


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


async def get_my_usage(
    authorization: str, start: str | None = None, end: str | None = None
) -> dict | None:
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


# ============================================================================
# Memories — long-term agent memory (Phase 1, tool-gated retrieval)
# ============================================================================
# Same critical-path error policy as slides: every response goes
# through ``_check_response`` so 4xx detail strings reach the agent
# loop as actionable ValueErrors. Phase 1 covers list / get / upsert /
# delete for both scopes; no update endpoint distinct from upsert
# because the common path is "save by slug, overwrite if exists."


async def list_user_memories(authorization: str, user_oid: str) -> list[dict]:
    """Return the index of a user's memories (slugs + descriptions + bodies).

    Bodies are included by the underlying endpoint but the model-facing
    tool projects to {slug, type, name, description} to keep the
    streamed result small.
    """
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{_get_base_url()}/api/users/{user_oid}/memories",
            headers={"Authorization": authorization},
        )
        _check_response(resp)
        return resp.json().get("memories", [])


async def get_user_memory(
    authorization: str,
    user_oid: str,
    slug: str,
) -> dict | None:
    """Fetch one user memory by slug. Returns None on 404."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{_get_base_url()}/api/users/{user_oid}/memories/{slug}",
            headers={"Authorization": authorization},
        )
        if resp.status_code == 404:
            return None
        _check_response(resp)
        return resp.json()


async def upsert_user_memory(
    authorization: str,
    user_oid: str,
    *,
    slug: str,
    type: str,
    name: str,
    description: str,
    body: str,
) -> dict:
    """Insert or update a user memory by slug."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{_get_base_url()}/api/users/{user_oid}/memories",
            headers={"Authorization": authorization},
            json={
                "slug": slug,
                "type": type,
                "name": name,
                "description": description,
                "body": body,
            },
        )
        _check_response(resp)
        return resp.json()


async def delete_user_memory(
    authorization: str,
    user_oid: str,
    slug: str,
) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.delete(
            f"{_get_base_url()}/api/users/{user_oid}/memories/{slug}",
            headers={"Authorization": authorization},
        )
        _check_response(resp)


async def list_project_memories(
    authorization: str,
    project_id: str,
) -> list[dict]:
    """Return the index of a project's memories."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{_get_base_url()}/api/projects/{project_id}/memories",
            headers={"Authorization": authorization},
        )
        _check_response(resp)
        return resp.json().get("memories", [])


async def get_project_memory(
    authorization: str,
    project_id: str,
    slug: str,
) -> dict | None:
    """Fetch one project memory by slug. Returns None on 404."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{_get_base_url()}/api/projects/{project_id}/memories/{slug}",
            headers={"Authorization": authorization},
        )
        if resp.status_code == 404:
            return None
        _check_response(resp)
        return resp.json()


async def upsert_project_memory(
    authorization: str,
    project_id: str,
    *,
    slug: str,
    type: str,
    name: str,
    description: str,
    body: str,
) -> dict:
    """Insert or update a project memory by slug. The DB service records
    ``created_by_user_id`` from the JWT — we don't pass it explicitly."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{_get_base_url()}/api/projects/{project_id}/memories",
            headers={"Authorization": authorization},
            json={
                "slug": slug,
                "type": type,
                "name": name,
                "description": description,
                "body": body,
            },
        )
        _check_response(resp)
        return resp.json()


async def delete_project_memory(
    authorization: str,
    project_id: str,
    slug: str,
) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.delete(
            f"{_get_base_url()}/api/projects/{project_id}/memories/{slug}",
            headers={"Authorization": authorization},
        )
        _check_response(resp)
        resp.raise_for_status()


# ---------------------------------------------------------------------------
# Masters
# ---------------------------------------------------------------------------
#
# All five HTTP methods here go through the same critical-path policy
# as projects/conversations/slides: ``raise_for_status`` so failures
# surface to the agent loop. Best-effort would silently break a deck
# Generate-Slide turn.


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
