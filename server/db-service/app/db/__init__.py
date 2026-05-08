"""Database layer — pool, config, and table repositories."""

from __future__ import annotations

import logging

from app.db.config import PostgresConfig
from app.db.pool import Pool, get_pool, close_pool
from app.db.redis import (
    RedisConfig,
    get_redis,
    init_redis,
    close_redis,
    cache_get_json,
    cache_set_json,
    cache_del,
)

log = logging.getLogger(__name__)

__all__ = [
    "PostgresConfig",
    "Pool",
    "get_pool",
    "close_pool",
    "init_db",
    "close_db",
    "RedisConfig",
    "get_redis",
    "init_redis",
    "close_redis",
    "cache_get_json",
    "cache_set_json",
    "cache_del",
]


async def init_db() -> Pool:
    pool = await get_pool()
    log.info("Database pool initialised (size=%d)", pool.size)
    await init_redis()
    return pool


async def close_db() -> None:
    await close_pool()
    await close_redis()
    log.info("Database pool closed")
