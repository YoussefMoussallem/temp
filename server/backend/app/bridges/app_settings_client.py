"""Process-local cache + httpx client for the db-service ``GET /api/settings/models`` endpoint.

Why a cache here too (db-service already has Redis):
* Avoids the per-turn cross-service hop for a value that changes
  on the order of weeks (admin tweaks).
* Keeps the LLM hot path free of an extra network round-trip.

Why a short TTL instead of explicit invalidation:
* Backend has no signal channel from db-service — the admin update
  happens in the *other* SPA, on the *other* origin. A 60s TTL means
  an admin's change is live everywhere within a minute without any
  pub/sub plumbing.

Resolution semantics, mirroring the historical fallbacks the env-only
code path used:
* ``default_model``: empty → ``settings.ai.default_model`` (env).
* ``search_model``:  empty → fall back to ``default_model`` resolved value.
* ``export_model``:  empty → fall back to ``default_model`` resolved value.
* ``title_model``:   empty → fall back to ``default_model`` resolved value.

Failure mode: any error fetching from db-service degrades to
"return env defaults", because a stuck admin-config call must never
break a live ``/turn``.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import httpx

from app.config import get_settings
from app_logger import get_logger

log = get_logger(__name__)


# Cache lifetime. Trades freshness for hot-path latency. 60s means an
# admin model swap propagates to every running backend within a minute
# without any explicit invalidation channel between services.
_TTL_SECONDS = 60.0
# Hard timeout on the db-service call — short enough that a stuck
# call never noticeably delays a /turn (we degrade to env on
# timeout). 2s is generous for a localhost / VNet-close service.
_REQUEST_TIMEOUT_S = 2.0

_lock = asyncio.Lock()


@dataclass
class ModelDefaults:
    """Resolved model identifiers for a single turn.

    All four fields are guaranteed non-empty strings — fallback chain
    has already been applied (search/export/title → default → env).

    ``title_model`` is used by the conversation auto-title flow only
    (``POST /api/agent/conversations/{id}/generate-title``); main-loop
    turns never read it. Kept here rather than in a sibling resolver
    so admins can configure all four in one round-trip.
    """
    default_model: str
    search_model: str
    export_model: str
    title_model: str


_cached_raw: dict[str, str] | None = None
_cached_at: float = 0.0


async def _fetch_raw(authorization: str) -> dict[str, str] | None:
    """Hit db-service and return the raw ``{key: value}`` map, or ``None`` on failure."""
    base = get_settings().app.db_service_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_S) as client:
            resp = await client.get(
                f"{base}/api/settings/models",
                headers={"Authorization": authorization} if authorization else {},
            )
            resp.raise_for_status()
            payload = resp.json()
    except Exception:
        log.warning(
            "Failed to fetch model settings from db-service; "
            "falling back to env defaults",
            exc_info=True,
        )
        return None
    if not isinstance(payload, dict):
        return None
    return {str(k): str(v or "") for k, v in payload.items()}


async def _get_raw_cached(authorization: str) -> dict[str, str]:
    """Return the cached raw map, refreshing on TTL expiry.

    On any fetch failure (transient db-service blip) we serve the last
    known good value if there is one; otherwise an empty dict so the
    fallback chain in ``resolve`` lands on env defaults.
    """
    global _cached_raw, _cached_at

    now = time.monotonic()
    if _cached_raw is not None and (now - _cached_at) < _TTL_SECONDS:
        return _cached_raw

    async with _lock:
        # Double-check after acquiring lock — another caller may have
        # refreshed while we waited.
        now = time.monotonic()
        if _cached_raw is not None and (now - _cached_at) < _TTL_SECONDS:
            return _cached_raw

        fresh = await _fetch_raw(authorization)
        if fresh is not None:
            _cached_raw = fresh
            _cached_at = now
        elif _cached_raw is None:
            # First-ever fetch failed — cache an empty map so we don't
            # spin re-trying on every turn. The next TTL window will
            # try again. Resolution falls through to env.
            _cached_raw = {}
            _cached_at = now
        return _cached_raw


def _env_default() -> str:
    return get_settings().ai.default_model


async def resolve(authorization: str = "") -> ModelDefaults:
    """Return the three resolved model ids for this request.

    ``authorization`` is forwarded to db-service so the backend doesn't
    need a service token — the user's bearer is already on the
    request that triggered the call. Reads from a TTL cache; refresh
    happens at most once per ``_TTL_SECONDS`` per process.
    """
    raw = await _get_raw_cached(authorization)

    env_default = _env_default()
    default_model = (raw.get("default_model") or "").strip() or env_default
    # Search & export & title fall back to the resolved default model
    # rather than env so the admin only needs to set ``default_model``
    # to configure all four (they pick the same model for everything).
    search_model = (raw.get("search_model") or "").strip() or default_model
    export_model = (raw.get("export_model") or "").strip() or default_model
    title_model = (raw.get("title_model") or "").strip() or default_model

    return ModelDefaults(
        default_model=default_model,
        search_model=search_model,
        export_model=export_model,
        title_model=title_model,
    )


def invalidate_cache() -> None:
    """Drop the in-process cache. Called by tests + on admin update via the proxy."""
    global _cached_raw, _cached_at
    _cached_raw = None
    _cached_at = 0.0
