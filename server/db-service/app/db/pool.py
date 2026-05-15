"""Async connection pool backed by asyncpg."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import asyncpg

from app.db.config import PostgresConfig

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None
_lock = asyncio.Lock()


class Pool:
    """Thin wrapper around an ``asyncpg.Pool`` with lifecycle helpers."""

    def __init__(self, inner: asyncpg.Pool) -> None:
        self._inner = inner

    async def fetch(self, query: str, *args: Any) -> list[asyncpg.Record]:
        return await self._inner.fetch(query, *args)

    async def fetchrow(self, query: str, *args: Any) -> asyncpg.Record | None:
        return await self._inner.fetchrow(query, *args)

    async def fetchval(self, query: str, *args: Any) -> Any:
        return await self._inner.fetchval(query, *args)

    async def execute(self, query: str, *args: Any) -> str:
        return await self._inner.execute(query, *args)

    async def executemany(self, query: str, args: list[tuple]) -> None:
        await self._inner.executemany(query, args)

    def acquire(self):
        """Acquire a connection from the pool (use as async context manager)."""
        return self._inner.acquire()

    async def close(self) -> None:
        await self._inner.close()
        logger.info("Connection pool closed")

    @property
    def size(self) -> int:
        return self._inner.get_size()

    @property
    def idle(self) -> int:
        return self._inner.get_idle_size()


async def get_pool(config: PostgresConfig | None = None) -> Pool:
    """Return the singleton pool, creating it on first call."""
    global _pool

    if _pool is not None and not _pool.is_closing():
        return Pool(_pool)

    async with _lock:
        if _pool is not None and not _pool.is_closing():
            return Pool(_pool)

        cfg = config or PostgresConfig()
        logger.info(
            "Creating connection pool: %s:%d/%s (min=%d, max=%d)",
            cfg.host,
            cfg.port,
            cfg.database,
            cfg.min_pool_size,
            cfg.max_pool_size,
        )
        connect_kwargs: dict[str, Any] = {}
        if cfg.use_entra_auth:
            connect_kwargs["password"] = cfg.get_entra_token
            connect_kwargs["ssl"] = True
        elif cfg.ssl:
            connect_kwargs["ssl"] = True
        _pool = await asyncpg.create_pool(
            dsn=cfg.connection_dsn,
            min_size=cfg.min_pool_size,
            max_size=cfg.max_pool_size,
            **connect_kwargs,
        )
        return Pool(_pool)


async def close_pool() -> None:
    """Shut down the singleton pool if it exists."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
