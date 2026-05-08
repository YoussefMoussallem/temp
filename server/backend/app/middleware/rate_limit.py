"""Dual-axis rate limiting: independent buckets per IP *and* per user.

Why two axes
------------
A single keying axis always misses one attack class:

* IP-only: one user spamming from many IPs (rotating proxies, leaked
  credentials abused from different machines) sneaks past.
* User-only: anonymous flooding (hammering ``/health``, login bursts,
  scraper bots that don't bother with auth) is invisible.

So we run *two* independent moving-window buckets per request. Either
tripping returns 429 with ``Retry-After``. The buckets are sized
loosely — see ``DEFAULT_*_LIMITS`` below — to stay invisible during
normal interactive use.

Defaults (loose, intentionally)
-------------------------------
* IP   : ``300/minute`` + ``5000/hour``
* User : ``300/minute`` + ``5000/hour``

A normal user sends ~5–10 chat turns/minute. 300 leaves ~30x headroom,
which is what "non-aggressive" means: the limits only fire on
something genuinely automated (loops, scripts, runaway clients).

Per-route stricter limits
-------------------------
Specific expensive endpoints layer additional ``@limiter.limit(...)``
decorators on top of these defaults. See per-route comments at the
decoration site (``/agent/turn``, ``/agent/export-deck``).

Implementation: raw ASGI middleware
-----------------------------------
``BaseHTTPMiddleware`` buffers streaming response bodies, which would
break the SSE on ``/agent/turn``. We use raw ASGI like
``RequestContextMiddleware`` does. Limit checks happen on request
entry only — the response body is forwarded untouched, so SSE flows
through fine.

User keying without parsing the JWT
-----------------------------------
We hash the bearer token (sha256, first 16 hex chars) instead of
decoding it. The route's ``get_current_user`` dependency still
validates the JWT; the keyer just needs a stable per-token bucket
without a duplicate JWKS round-trip at middleware stage. Re-issued
tokens land in a fresh bucket — fine, that's a new session.

Storage / topology
------------------
In-memory ``MemoryStorage``, single-process. Same single-replica
constraint documented in ``architecture-phase3.mdc`` and
``service-split-rejected.mdc``. If the backend ever scales
horizontally, swap to ``RedisStorage`` so all replicas share a
counter.
"""

from __future__ import annotations

import hashlib
from typing import Iterable

from fastapi import FastAPI
from limits import RateLimitItem, parse_many
from limits.storage import MemoryStorage
from limits.strategies import MovingWindowRateLimiter
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

DEFAULT_IP_LIMITS: list[str] = ["300/minute", "5000/hour"]
DEFAULT_USER_LIMITS: list[str] = ["300/minute", "5000/hour"]


# ---------------------------------------------------------------------------
# Key extraction
# ---------------------------------------------------------------------------


def _user_token_hash(request: Request) -> str | None:
    """sha256(bearer_token)[:16] when one is present, else None."""
    auth = request.headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        token = auth.split(" ", 1)[1].strip()
        if token:
            return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
    return None


def user_or_ip_key(request: Request) -> str:
    """For per-route ``@limiter.limit`` decorators on authenticated routes.

    Prefers a user-derived key (token hash) when the caller is
    authenticated. Falls back to IP otherwise — keeps unauthenticated
    health checks etc. covered.
    """
    uk = _user_token_hash(request)
    if uk:
        return f"u:{uk}"
    return f"ip:{get_remote_address(request)}"


# ---------------------------------------------------------------------------
# Dual-axis ASGI middleware
# ---------------------------------------------------------------------------


class DualAxisRateLimitMiddleware:
    """Independently rate-limit by IP *and* (when present) by user.

    Two separate moving-window buckets are checked per request. The IP
    bucket always runs; the user bucket only runs when an
    ``Authorization: Bearer …`` header is present. Either bucket
    tripping short-circuits with a 429 + ``Retry-After``.
    """

    def __init__(
        self,
        app: ASGIApp,
        ip_limits: Iterable[str] | None = None,
        user_limits: Iterable[str] | None = None,
    ) -> None:
        ip_limits = ip_limits if ip_limits is not None else DEFAULT_IP_LIMITS
        user_limits = user_limits if user_limits is not None else DEFAULT_USER_LIMITS
        self.app = app
        storage = MemoryStorage()
        self._strategy = MovingWindowRateLimiter(storage)
        self._ip_limits: list[RateLimitItem] = list(parse_many("; ".join(ip_limits)))
        self._user_limits: list[RateLimitItem] = list(parse_many("; ".join(user_limits)))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        ip = get_remote_address(request)

        for item in self._ip_limits:
            if not self._strategy.hit(item, "ip", ip):
                response = _too_many(item, "ip")
                await response(scope, receive, send)
                return

        uk = _user_token_hash(request)
        if uk:
            for item in self._user_limits:
                if not self._strategy.hit(item, "user", uk):
                    response = _too_many(item, "user")
                    await response(scope, receive, send)
                    return

        await self.app(scope, receive, send)


def _too_many(item: RateLimitItem, axis: str) -> JSONResponse:
    """Build a 429 response with ``Retry-After`` for a tripped bucket."""
    retry_after = max(1, int(item.get_expiry()))
    return JSONResponse(
        status_code=429,
        content={
            "detail": f"Rate limit exceeded ({axis}): {item}",
            "axis": axis,
        },
        headers={"Retry-After": str(retry_after)},
    )


# ---------------------------------------------------------------------------
# SlowAPI limiter — used solely for per-route ``@limiter.limit(...)`` decorators
#
# ``default_limits=[]`` so SlowAPI does NOTHING globally; the dual-axis
# middleware above owns the global defaults. Each per-route decorator
# passes its own ``key_func`` — keep them user-keyed for authenticated
# endpoints (more accurate than IP behind shared NATs).
# ---------------------------------------------------------------------------
limiter = Limiter(
    key_func=user_or_ip_key,
    default_limits=[],
)


def register_rate_limiting(app: FastAPI) -> None:
    """Wire dual-axis defaults + SlowAPI per-route decorators into the app.

    Middleware order (Starlette wraps in reverse of add order):

      Request flow:  CORS -> DualAxis (global IP+user) -> SlowAPI (per-route) -> app

    So we add SlowAPI first (innermost) and DualAxis on top. ``main.py``
    layers CORS and ``RequestContext`` outside of these.
    """
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)
    app.add_middleware(DualAxisRateLimitMiddleware)
