"""Process-wide asyncpg pool with a narrow, typed wrapper.

The module exposes a single lazily-initialised pool via :func:`get_pool`.
Callers receive a :class:`Pool` wrapper rather than the raw ``asyncpg.Pool``
so query helpers stay uniform across services and the surface area we rely on
is explicit (easier to mock and easier to swap the driver later).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import asyncpg

from postgresql.config import PostgresConfig

logger = logging.getLogger(__name__)

# Module-level singletons: one pool per process. ``_lock`` guards the
# create-on-first-use path so concurrent startup tasks don't race on init.
_pool: asyncpg.Pool | None = None
_lock = asyncio.Lock()


class Pool:
    """Thin wrapper around an ``asyncpg.Pool`` with lifecycle helpers.

    Exists for two reasons:

    1. A deliberately small query surface (fetch / fetchrow / fetchval /
       execute / executemany / acquire) so application code doesn't depend on
       asyncpg internals it doesn't actually need.
    2. Cheap to construct — each call to :func:`get_pool` returns a fresh
       wrapper around the shared underlying pool, so the wrapper can be passed
       through DI without worrying about shared mutable state.
    """

    def __init__(self, inner: asyncpg.Pool) -> None:
        self._inner = inner

    # ── Query helpers ───────────────────────────────────────────────
    #
    # All helpers delegate straight to asyncpg; they exist so callers can
    # depend on :class:`Pool` rather than pulling asyncpg types into their
    # own signatures.

    async def fetch(self, query: str, *args: Any) -> list[asyncpg.Record]:
        """Run *query* and return every row."""
        return await self._inner.fetch(query, *args)

    async def fetchrow(self, query: str, *args: Any) -> asyncpg.Record | None:
        """Run *query* and return the first row, or ``None`` if there is none."""
        return await self._inner.fetchrow(query, *args)

    async def fetchval(self, query: str, *args: Any) -> Any:
        """Run *query* and return the first column of the first row."""
        return await self._inner.fetchval(query, *args)

    async def execute(self, query: str, *args: Any) -> str:
        """Run *query* for its side effect and return the status tag."""
        return await self._inner.execute(query, *args)

    async def executemany(self, query: str, args: list[tuple]) -> None:
        """Run *query* once per argument tuple (batched INSERT/UPDATE)."""
        await self._inner.executemany(query, args)

    def acquire(self):
        """Acquire a connection from the pool (use as async context manager).

        Needed whenever a caller must pin multiple queries to one session —
        transactions, ``SET LOCAL``, advisory locks, ``LISTEN``/``NOTIFY``.
        """
        return self._inner.acquire()

    # ── Lifecycle ───────────────────────────────────────────────────

    async def close(self) -> None:
        """Close the underlying pool. Usually called via :func:`close_pool`."""
        await self._inner.close()
        logger.info("Connection pool closed")

    @property
    def size(self) -> int:
        """Total number of connections currently held by the pool."""
        return self._inner.get_size()

    @property
    def idle(self) -> int:
        """Connections sitting idle in the pool (useful for saturation checks)."""
        return self._inner.get_idle_size()


async def get_pool(config: PostgresConfig | None = None) -> Pool:
    """Return the singleton pool, creating it on first call.

    The fast path (pool exists, not closing) skips the lock entirely. The
    slow path double-checks under the lock so two concurrent startup tasks
    don't each create a pool. If a previous pool was closed (e.g. tests),
    a fresh one is built.

    Args:
        config: Optional override. If omitted, :class:`PostgresConfig` is
            loaded from the environment — the normal production path.
    """
    global _pool

    if _pool is not None and not _pool.is_closing():
        return Pool(_pool)

    async with _lock:
        # Re-check after acquiring the lock: another task may have created
        # the pool while we were waiting.
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
        _pool = await asyncpg.create_pool(
            dsn=cfg.connection_dsn,
            min_size=cfg.min_pool_size,
            max_size=cfg.max_pool_size,
        )
        return Pool(_pool)


async def close_pool() -> None:
    """Shut down the singleton pool if it exists.

    Safe to call more than once and safe to call when no pool was ever
    created — useful from lifespan shutdown hooks and test teardown.
    """
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
