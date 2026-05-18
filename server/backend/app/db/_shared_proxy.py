"""Shared internals for the FE-proxy router surface.

The HTTP-proxy router in each domain file (e.g. ``@router.get
("/projects/{project_id}/slides")``) uses these helpers:

  * ``_get_client()`` — process-wide ``httpx.AsyncClient`` (pooled).
  * ``_db_url()`` — db-service base URL, no trailing slash.
  * ``_proxy()`` — forward one request, return ``(status_code, body)``.
  * ``_proxy_get()`` — GET shorthand: raises on 4xx/5xx, returns body.
  * ``_date_params()`` — drop None/empty values from a {start, end}
    dict so the db-service doesn't see ``start=`` as "filter by empty
    date".

Helpers for the *typed-client* surface live in ``_shared.py``. The two
files don't share helpers because the typed client uses one-shot
``async with httpx.AsyncClient(...)`` per call (small N, isolation
preferred) while the proxy uses a pooled client (high N, connection
reuse preferred).
"""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import HTTPException

from app.config import get_settings


# Shared client — keeping a pool of connections to db-service avoids paying
# TCP connect + handshake on every CRUD call (saved per-call latency on
# localhost is small but noticeable; across a network it's significant).
# The client is lazily constructed on first use so import-time side effects
# stay minimal; there is no explicit shutdown hook, which is fine because
# httpx.AsyncClient cleans up on process exit.
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    """Return the process-wide httpx client, creating it on first call."""
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=10)
    return _client


def _db_url() -> str:
    """Base URL of the db-service, without a trailing slash."""
    return get_settings().app.db_service_url.rstrip("/")


async def _proxy(
    method: str,
    path: str,
    authorization: str | None,
    *,
    params: dict | None = None,
    json_body: Any = None,
) -> tuple[int, Any]:
    """Forward a single request to the DB service.

    Returns ``(status_code, body)`` where body is parsed JSON when the
    response has a JSON payload, the raw text if JSON parsing fails, or
    ``None`` for 204 / empty bodies.

    Error handling strategy:
      * Network / connection failure -> raise 502 (caller sees the DB
        service as unavailable, not a 500 from us).
      * DB 401/403/404 -> re-raise with the same status so the frontend
        can react appropriately (e.g. force re-login on 401).
      * DB 5xx -> raise 502; we don't want to surface the DB service's
        internal failures as our own 500s.
      * 2xx / 3xx -> return (status, body) and let the caller decide.
    """
    headers = {}
    if authorization:
        # Passthrough only; the DB service validates the token.
        headers["Authorization"] = authorization
    try:
        resp = await _get_client().request(
            method,
            f"{_db_url()}{path}",
            headers=headers,
            params=params or {},
            json=json_body,
        )
    except Exception:
        # Connection refused, DNS failure, timeout, etc. - treat the DB
        # service as down from the caller's perspective.
        raise HTTPException(status_code=502, detail="DB service unavailable")

    if resp.status_code == 401:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if resp.status_code == 403:
        raise HTTPException(status_code=403, detail=resp.text or "Forbidden")
    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail=resp.text or "Not found")
    if resp.status_code >= 500:
        # Collapse all DB 5xx to 502 - the failure is downstream of us.
        raise HTTPException(status_code=502, detail="DB service error")

    if resp.status_code == 204 or not resp.content:
        return resp.status_code, None
    try:
        return resp.status_code, resp.json()
    except Exception:
        # Non-JSON success body (rare) - hand back the raw text instead
        # of crashing the proxy.
        return resp.status_code, resp.text


async def _proxy_get(path: str, authorization: str | None, params: dict | None = None) -> dict:
    """GET helper: forwards the request and raises on any 4xx/5xx.

    Unlike ``_proxy``, which returns the status so the caller can branch,
    this helper assumes the caller only wants the success body. Use it
    for plain read endpoints.
    """
    status, body = await _proxy("GET", path, authorization, params=params)
    if status >= 400:
        raise HTTPException(status_code=status, detail=str(body))
    return body  # type: ignore[return-value]


def _date_params(start: str | None, end: str | None) -> dict:
    """Build a query-param dict, omitting keys whose value is None/empty.

    Several admin / usage endpoints accept an optional date window.
    Sending ``start=`` with an empty string would be parsed as "filter
    by empty date" on the DB side, so we drop missing values entirely.
    """
    params = {}
    if start:
        params["start"] = start
    if end:
        params["end"] = end
    return params
