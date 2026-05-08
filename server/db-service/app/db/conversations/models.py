"""Conversation entity — typed representation of a conversations table row."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

import asyncpg


@dataclass(frozen=True)
class Conversation:
    id: UUID
    project_id: UUID
    title: str
    created_at: datetime
    last_active_at: datetime
    message_count: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: Decimal

    @classmethod
    def from_record(cls, record: asyncpg.Record) -> Conversation:
        return cls(
            id=record["id"],
            project_id=record["project_id"],
            title=record["title"],
            created_at=record["created_at"],
            last_active_at=record["last_active_at"],
            message_count=record["message_count"],
            total_input_tokens=record["total_input_tokens"],
            total_output_tokens=record["total_output_tokens"],
            total_cost_usd=record["total_cost_usd"],
        )
