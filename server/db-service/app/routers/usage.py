"""Usage recording and query endpoints."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.db import Pool, get_pool
from app.db.users.repository import get_or_create_user
from app.db.usage_records.repository import (
    record_usage as db_record_usage,
    get_for_user,
    get_totals_for_user,
    get_all_totals,
)
from app.dependencies import CurrentUser, get_current_user

router = APIRouter(prefix="/usage", tags=["usage"])


class RecordUsageRequest(BaseModel):
    user_id: str
    email: str
    display_name: str | None = None
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


def _default_start() -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=30)


def _default_end() -> datetime:
    return datetime.now(timezone.utc)


def _serialize(obj) -> dict:
    d = asdict(obj) if hasattr(obj, "__dataclass_fields__") else dict(obj)
    for k, v in d.items():
        if isinstance(v, datetime):
            d[k] = v.isoformat()
        elif isinstance(v, Decimal):
            d[k] = str(v)
        elif isinstance(v, UUID):
            d[k] = str(v)
    return d


@router.post("/record")
async def record_usage(body: RecordUsageRequest):
    """Record one usage entry. Called by consuming services."""
    pool: Pool = await get_pool()
    db_user = await get_or_create_user(
        pool,
        azure_oid=body.user_id,
        email=body.email,
        display_name=body.display_name,
    )
    record = await db_record_usage(
        pool,
        user_id=db_user.azure_oid,
        model=body.model,
        input_tokens=body.input_tokens,
        output_tokens=body.output_tokens,
        cost_usd=body.cost_usd,
    )
    return _serialize(record)


@router.get("/me")
async def my_usage(
    user: CurrentUser = Depends(get_current_user),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
):
    """Return the current user's usage records and per-model totals."""
    pool: Pool = await get_pool()
    period_start = start or _default_start()
    period_end = end or _default_end()

    db_user = await get_or_create_user(
        pool,
        azure_oid=user.azure_oid or user.user_id,
        email=user.email,
        display_name=user.display_name,
    )

    records = await get_for_user(
        pool,
        user_id=db_user.azure_oid,
        start=period_start,
        end=period_end,
    )
    totals = await get_totals_for_user(
        pool,
        user_id=db_user.azure_oid,
        start=period_start,
        end=period_end,
    )

    return {
        "user_id": db_user.azure_oid,
        "email": db_user.email,
        "period": {
            "start": period_start.isoformat(),
            "end": period_end.isoformat(),
        },
        "totals": [_serialize(t) for t in totals],
        "records": [_serialize(r) for r in records],
    }


@router.get("/admin")
async def admin_usage(
    _: CurrentUser = Depends(get_current_user),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
):
    """Return per-user aggregate totals."""
    pool: Pool = await get_pool()
    period_start = start or _default_start()
    period_end = end or _default_end()

    totals = await get_all_totals(pool, start=period_start, end=period_end)

    return {
        "period": {
            "start": period_start.isoformat(),
            "end": period_end.isoformat(),
        },
        "users": [_serialize(t) for t in totals],
    }
