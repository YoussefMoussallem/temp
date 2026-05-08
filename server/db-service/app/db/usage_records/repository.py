"""Usage records repository — all usage DB operations."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.db import Pool
from app.db.usage_records import queries
from app.db.usage_records.models import UsageRecord


async def record_usage(
    pool: Pool,
    *,
    user_id: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float | Decimal,
) -> UsageRecord:
    """Write one usage record."""
    row = await pool.fetchrow(
        queries.INSERT_RECORD,
        user_id,
        model,
        input_tokens,
        output_tokens,
        Decimal(str(cost_usd)),
    )
    return UsageRecord.from_record(row)


async def get_for_user(
    pool: Pool,
    *,
    user_id: str,
    start: datetime,
    end: datetime,
) -> list[UsageRecord]:
    """Return raw usage records for a user within a date range."""
    rows = await pool.fetch(queries.SELECT_FOR_USER, user_id, start, end)
    return [UsageRecord.from_record(r) for r in rows]


async def get_totals_for_user(
    pool: Pool,
    *,
    user_id: str,
    start: datetime,
    end: datetime,
) -> list[dict]:
    """Return per-model aggregate totals for a user."""
    rows = await pool.fetch(queries.TOTALS_FOR_USER, user_id, start, end)
    return [dict(r) for r in rows]


async def get_all_totals(
    pool: Pool,
    *,
    start: datetime,
    end: datetime,
) -> list[dict]:
    """Return per-user aggregate totals across all users."""
    rows = await pool.fetch(queries.ALL_USER_TOTALS, start, end)
    return [dict(r) for r in rows]


async def get_all_records_with_user(
    pool: Pool,
    *,
    start: datetime,
    end: datetime,
) -> list[dict]:
    """Return all usage records joined with user info."""
    rows = await pool.fetch(queries.ALL_RECORDS_WITH_USER, start, end)
    return [dict(r) for r in rows]


async def get_aggregate_stats(
    pool: Pool,
    *,
    start: datetime,
    end: datetime,
) -> dict:
    """Return aggregate stats across all usage records."""
    row = await pool.fetchrow(queries.AGGREGATE_STATS, start, end)
    return dict(row) if row else {}
