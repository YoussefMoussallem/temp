"""Usage — billing/telemetry record + dashboard fetch.

Both surfaces in one file:

  * Typed client (``record_usage``, ``get_my_usage``) — used by the
    /turn handler to log every model call.
  * FE proxy (``GET /usage/me``) — the dashboard reads through the
    typed client (not the generic ``_proxy``) because we want the
    empty-state shape on failure, not a 502.
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Header, Query

from ._shared import _get_base_url, log


# ===========================================================================
# Typed client — used by backend code (agent tools, /turn handler, services)
# ===========================================================================


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

    Returns ``None`` on failure; the caller (``_route_my_usage`` below)
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


# ===========================================================================
# FastAPI router — FE proxy (mounted at /api/db/usage/...)
# ===========================================================================
#
# `/usage/me` goes through the typed bridge (`get_my_usage`) rather than
# the generic `_proxy_get` because the frontend expects a specific
# empty-state shape on failure.

router = APIRouter(tags=["db"])


@router.get("/usage/me")
async def _route_my_usage(
    authorization: str | None = Header(default=None),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
):
    """Return the caller's own token/usage records, optionally date-windowed.

    On DB failure we return an empty-but-valid shape instead of 502 so
    the dashboard can render gracefully. This is a deliberate exception
    to the usual "surface errors upward" rule in this module.
    """
    result = await get_my_usage(authorization or "", start=start, end=end)
    if result is None:
        return {"error": "Failed to fetch usage data", "totals": [], "records": []}
    return result
