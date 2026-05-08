"""Message entity — typed representation of a messages table row.

``content`` is always a JSON-decoded list of Anthropic-shaped content blocks
(text, tool_use, tool_result). Stored as JSONB; asyncpg returns it as a str
unless a codec is registered, so repositories decode it explicitly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg


@dataclass(frozen=True)
class Message:
    id: UUID
    conversation_id: UUID
    sequence: int
    role: str
    content: list[dict[str, Any]]
    created_at: datetime

    @classmethod
    def from_record(cls, record: asyncpg.Record) -> Message:
        raw = record["content"]
        content = json.loads(raw) if isinstance(raw, str) else raw
        return cls(
            id=record["id"],
            conversation_id=record["conversation_id"],
            sequence=record["sequence"],
            role=record["role"],
            content=content,
            created_at=record["created_at"],
        )
