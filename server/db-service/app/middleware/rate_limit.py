"""Dual-axis rate limiting for db-service: independent IP + user buckets.

Why two axes
------------
db-service is internal — only the backend talks to it. Every request
arrives from the backend's IP, so an IP-only limiter would put all
users into one shared bucket. A user-only limiter, conversely, is
blind to the backend going completely berserk (a runaway loop in
``query_loop`` could fan out into thousands of db calls/sec under a
single auth header).

So we run *two* independent moving-window buckets:

* IP   : effectively a global circuit breaker for the whole backend.
  Loose — one user-facing turn fans out to ~5–10 db calls and the
  backend caps at 300 turns/min/user — so this needs lots of headroom.
* User : per-user fairness across the backend's traffic.

Either bucket tripping returns 429 with ``Retry-After``.

Defaults (loose, intentionally)
-------------------------------
* IP   : ``6000/minute``  + ``100000/hour``
* User : ``600/minute``   + ``10000/hour``

The user limit is ~10x the backend's user-facing limit (``300/min``),
which leaves comfortable room for the per-turn db fan-out. The IP
limit is sized to handle ~10 concurrently active users at peak load
without ever firing during normal traffic — it's a safety net, not a
fairness mechanism.

User keying without parsing the JWT
-----------------------------------
We hash the bearer token (sha256, first 16 hex chars). The route's
``get_current_user`` dependency still validates the JWT; the keyer
just needs a stable per-token bucket without re-validating at the
middleware stage.

Implementation: raw ASGI middleware
-----------------------------------
``BaseHTTPMiddleware`` buffers streaming response bodies. db-service
doesn't currently stream, but using raw ASGI keeps the door open and
matches the backend's ``DualAxisRateLimitMiddleware``.

Storage / topology
------------------
In-memory, single-process. Per ``architecture-phase3.mdc`` and
``service-split-rejected.mdc`` the deployment target is single-replica.
Swap to Redis (already on db-service as a read cache) if the service
ever scales horizontally.
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

DEFAULT_IP_LIMITS: list[str] = ["6000/minute", "100000/hour"]
DEFAULT_USER_LIMITS: list[str] = ["600/minute", "10000/hour"]


def _user_token_hash(request: Request) -> str | None:
    auth = request.headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        token = auth.split(" ", 1)[1].strip()
        if token:
            return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
    return None


def user_or_ip_key(request: Request) -> str:
    """For per-route ``@limiter.limit`` decorators (none today, but kept
    available for stricter caps on specific db-service endpoints later)."""
    uk = _user_token_hash(request)
    if uk:
        return f"u:{uk}"
    return f"ip:{get_remote_address(request)}"


class DualAxisRateLimitMiddleware:
    """Independently rate-limit by IP *and* (when present) by user.

    Two separate moving-window buckets per request. Either bucket
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
    retry_after = max(1, int(item.get_expiry()))
    return JSONResponse(
        status_code=429,
        content={
            "detail": f"Rate limit exceeded ({axis}): {item}",
            "axis": axis,
        },
        headers={"Retry-After": str(retry_after)},
    )


# SlowAPI limiter — kept around for per-route ``@limiter.limit(...)`` decorators
# if/when db-service ever needs them. ``default_limits=[]`` means it's inert
# globally; the dual-axis middleware above owns the global defaults.
limiter = Limiter(
    key_func=user_or_ip_key,
    default_limits=[],
)


def register_rate_limiting(app: FastAPI) -> None:
    """Wire dual-axis defaults + SlowAPI per-route decorators into the app."""
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)
    app.add_middleware(DualAxisRateLimitMiddleware)
