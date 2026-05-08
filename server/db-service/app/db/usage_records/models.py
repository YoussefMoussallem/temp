"""UsageRecord entity model — typed representation of a usage_records table row."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

import asyncpg


@dataclass(frozen=True)
class UsageRecord:
    id: UUID
    user_id: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    recorded_at: datetime

    @classmethod
    def from_record(cls, record: asyncpg.Record) -> UsageRecord:
        return cls(
            id=record["id"],
            user_id=record["user_id"],
            model=record["model"],
            input_tokens=record["input_tokens"],
            output_tokens=record["output_tokens"],
            cost_usd=record["cost_usd"],
            recorded_at=record["recorded_at"],
        )
