"""Slide entity — typed representation of a slides table row."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import asyncpg


@dataclass(frozen=True)
class Slide:
    id: UUID
    project_id: UUID
    position: int
    title: str | None
    html: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(cls, record: asyncpg.Record) -> Slide:
        return cls(
            id=record["id"],
            project_id=record["project_id"],
            position=record["position"],
            title=record["title"],
            html=record["html"],
            created_at=record["created_at"],
            updated_at=record["updated_at"],
        )
