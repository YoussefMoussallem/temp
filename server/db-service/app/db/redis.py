"""Redis client + JSON cache helpers.

Redis is a read cache on top of Postgres, never the source of truth. Every
helper swallows connection/transient errors and logs a warning — a dropped
cache is always safe, so cache failures must never surface to callers.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from urllib.parse import urlparse

import redis.asyncio as aioredis
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.db.azure_auth import ManagedIdentityTokenProvider, REDIS_SCOPE

logger = logging.getLogger(__name__)

_client: aioredis.Redis | None = None
_lock = asyncio.Lock()

# When Redis is unreachable, every cache op degrades to pass-through. Keep
# the per-op wall-clock tiny so a downed Redis doesn't add seconds of
# latency to every DB write. 200ms is generous for a local/ping-close
# Redis and still snappy when it's missing entirely.
_CONNECT_TIMEOUT_S = 0.2
_SOCKET_TIMEOUT_S = 0.2
# Once we've seen N consecutive failures, stop attempting for a while —
# each attempt still costs a full timeout otherwise.
_CIRCUIT_BREAKER_THRESHOLD = 3
_CIRCUIT_BREAKER_COOLDOWN_S = 10.0


class RedisConfig(BaseSettings):
    """Redis connection config (env prefix ``REDIS_``)."""

    model_config = SettingsConfigDict(
        env_prefix="REDIS_",
        env_file=".env",
        extra="ignore",
    )

    url: str = "redis://localhost:6379/0"
    use_entra_auth: bool = False
    entra_client_id: str = ""
    entra_principal_id: str = ""

    def parsed_url(self):
        """Return parsed Redis URL components."""
        return urlparse(self.url)


# Module-global circuit breaker state. Shared across all cache helpers.
_consecutive_failures = 0
_circuit_open_until: float = 0.0


def _circuit_is_open() -> bool:
    if _consecutive_failures < _CIRCUIT_BREAKER_THRESHOLD:
        return False
    return asyncio.get_event_loop().time() < _circuit_open_until


def _record_failure() -> None:
    global _consecutive_failures, _circuit_open_until
    _consecutive_failures += 1
    if _consecutive_failures == _CIRCUIT_BREAKER_THRESHOLD:
        _circuit_open_until = asyncio.get_event_loop().time() + _CIRCUIT_BREAKER_COOLDOWN_S
        logger.warning(
            "Redis: %d consecutive failures — opening circuit for %.0fs",
            _consecutive_failures, _CIRCUIT_BREAKER_COOLDOWN_S,
        )


def _record_success() -> None:
    global _consecutive_failures, _circuit_open_until
    if _consecutive_failures > 0:
        logger.info("Redis: reachable again, closing circuit")
    _consecutive_failures = 0
    _circuit_open_until = 0.0


async def get_redis(config: RedisConfig | None = None) -> aioredis.Redis:
    """Return the singleton Redis client, connecting on first call."""
    global _client

    if _client is not None:
        return _client

    async with _lock:
        if _client is not None:
            return _client

        cfg = config or RedisConfig()
        logger.info("Connecting to Redis: %s", cfg.url)
        if cfg.use_entra_auth:
            parsed = cfg.parsed_url()
            if not cfg.entra_principal_id:
                raise ValueError("REDIS_ENTRA_PRINCIPAL_ID is required when REDIS_USE_ENTRA_AUTH=true")
            token_provider = ManagedIdentityTokenProvider(
                scope=REDIS_SCOPE,
                client_id=cfg.entra_client_id,
            )
            _client = aioredis.Redis(
                host=parsed.hostname,
                port=parsed.port or 10000,
                db=int((parsed.path or "/0").lstrip("/") or "0"),
                username=cfg.entra_principal_id,
                password=token_provider.get_token(),
                ssl=parsed.scheme == "rediss",
                decode_responses=True,
                socket_connect_timeout=_CONNECT_TIMEOUT_S,
                socket_timeout=_SOCKET_TIMEOUT_S,
            )
        else:
            _client = aioredis.from_url(
                cfg.url,
                decode_responses=True,
                socket_connect_timeout=_CONNECT_TIMEOUT_S,
                socket_timeout=_SOCKET_TIMEOUT_S,
            )
        return _client


async def init_redis() -> None:
    """Called from FastAPI lifespan. Pings Redis to fail loudly on misconfig,
    but a connection failure is logged (not raised) — the service still boots."""
    try:
        client = await get_redis()
        await client.ping()
        logger.info("Redis ready")
    except Exception as e:  # noqa: BLE001
        logger.warning("Redis unavailable at startup (degrading to pass-through): %s", e)


async def close_redis() -> None:
    global _client
    if _client is not None:
        try:
            await _client.aclose()
        except Exception as e:  # noqa: BLE001
            logger.warning("Error closing Redis: %s", e)
        _client = None
        logger.info("Redis client closed")


# ── Cache helpers ──────────────────────────────────────────────────────────
#
# All of these must be safe when Redis is down. Read misses return None,
# writes/deletes swallow the error. Callers treat cache as advisory.


async def cache_get_json(key: str) -> Any | None:
    """Fetch and JSON-decode. None on miss, connection error, or decode error."""
    if _circuit_is_open():
        return None
    try:
        client = await get_redis()
        raw = await client.get(key)
    except Exception as e:  # noqa: BLE001
        _record_failure()
        logger.debug("cache_get_json('%s') failed: %s", key, e)
        return None
    _record_success()
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except Exception:  # noqa: BLE001
        return None


async def _set_impl(key: str, value: Any, ttl: int) -> None:
    try:
        client = await get_redis()
        await client.set(key, json.dumps(value), ex=ttl)
        _record_success()
    except Exception as e:  # noqa: BLE001
        _record_failure()
        logger.debug("cache_set_json('%s') failed: %s", key, e)


async def _del_impl(keys: tuple[str, ...]) -> None:
    try:
        client = await get_redis()
        await client.delete(*keys)
        _record_success()
    except Exception as e:  # noqa: BLE001
        _record_failure()
        logger.debug("cache_del(%s) failed: %s", keys, e)


def cache_set_json(key: str, value: Any, ttl: int = 3600) -> None:
    """Fire-and-forget SET. Never blocks the caller.

    Cache is advisory — if the write lags behind the response, the worst
    case is one extra DB hit on the next read.
    """
    if _circuit_is_open():
        return
    asyncio.create_task(_set_impl(key, value, ttl))


def cache_del(*keys: str) -> None:
    """Fire-and-forget DEL. Never blocks the caller.

    Invalidation can trail the write by a few ms; readers will see stale
    data for that window, then re-populate from Postgres on the next read.
    """
    if not keys or _circuit_is_open():
        return
    asyncio.create_task(_del_impl(keys))
