"""Shared internals for the typed-client surface.

Every domain file's client functions reach for these. Public helpers for
the *router* surface live in ``_shared_proxy.py``.

  * ``_get_base_url()`` — cached db-service base URL.
  * ``_check_response()`` — translate 4xx with ``{"detail": "..."}``
    bodies into a clean ``ValueError(detail)`` so the agent loop sees
    actionable messages instead of opaque ``HTTPStatusError`` strings.
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

    **Scope.** Used by every critical-path bridge in the domain files.
    The best-effort tier (``record_usage`` / ``get_my_usage`` /
    ``validate_token`` / ``get_conversation`` /
    ``add_conversation_tokens`` / ``get_active_master_for_project``)
    intentionally wraps the whole call in ``try: … except Exception:
    log + return None``, so it doesn't need / want the extra
    translation step.

    **5xx note.** Left to ``raise_for_status()`` because the agent
    shouldn't try to "fix" a server bug — the default exception path
    surfaces the failure to the turn handler as-is.

    **404 callers.** Several ``get_*`` bridges treat 404 as "no such
    row, return None" rather than an error. Those still check
    ``resp.status_code == 404`` explicitly *before* calling this
    helper; the soft-404 isn't a property we bake in here because some
    endpoints (e.g. ``delete_*``) legitimately mean "the thing you're
    deleting must exist" and a 404 there really is an actionable error.
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
