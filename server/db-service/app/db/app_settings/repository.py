"""``app_settings`` repository — read-through Redis cache, DEL on write.

Postgres is the source of truth (per the project's persistence rule);
Redis is purely a read cache. Single shared cache key holds the full
key→value map so every reader can serve from one GET.
"""

from __future__ import annotations

import json
from typing import Any

from app.db import Pool, cache_del, cache_get_json, cache_set_json
from app.db.app_settings import queries

# Single key holds the whole map. The map is tiny (a handful of model-
# name strings today) so re-fetching the full set on miss is cheaper
# than maintaining N per-key cache entries with their own TTLs.
_CACHE_KEY = "cache:app_settings:all"
_CACHE_TTL_SECONDS = 300


async def get_all_settings(pool: Pool) -> dict[str, Any]:
    """Return ``{key: value}`` for every row in ``app_settings``.

    Read-through: serves from Redis on hit, falls back to Postgres on
    miss (and re-populates the cache). Returns an empty dict if the
    table is empty.
    """
    cached = await cache_get_json(_CACHE_KEY)
    if isinstance(cached, dict):
        return cached

    rows = await pool.fetch(queries.GET_ALL)
    out: dict[str, Any] = {}
    for r in rows:
        out[r["key"]] = _decode_value(r["value"])
    cache_set_json(_CACHE_KEY, out, ttl=_CACHE_TTL_SECONDS)
    return out


async def set_setting(
    pool: Pool, *, key: str, value: Any, updated_by: str | None
) -> dict[str, Any]:
    """Upsert one setting; busts the read cache.

    ``value`` is JSON-serialised before insertion so JSONB stores the
    actual shape (string, number, object) rather than a quoted Python
    repr. ``updated_by`` is the admin's azure_oid (or None for
    internal callers).
    """
    payload = json.dumps(value)
    row = await pool.fetchrow(queries.UPSERT, key, payload, updated_by)
    cache_del(_CACHE_KEY)
    return {
        "key": row["key"],
        "value": _decode_value(row["value"]),
        "updated_at": row["updated_at"],
        "updated_by": row["updated_by"],
    }


def _decode_value(raw: Any) -> Any:
    """asyncpg may return JSONB as a Python str (depending on codec).

    Normalise to the decoded JSON value so callers always see Python
    types (str / int / dict / list) — never a JSON-encoded string.
    """
    if isinstance(raw, (str, bytes)):
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return raw
    return raw
