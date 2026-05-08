"""Project entity — typed representation of a projects table row."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import asyncpg


@dataclass(frozen=True)
class Project:
    id: UUID
    user_id: str
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime
    role: str | None = None

    @classmethod
    def from_record(cls, record: asyncpg.Record) -> Project:
        # ``role`` is only present on queries that JOIN project_members
        # (i.e. ``LIST_BY_USER``). For raw INSERT / GET / UPDATE rows, the
        # column is absent and we leave it unset.
        try:
            role = record["role"]
        except (KeyError, IndexError):
            role = None
        return cls(
            id=record["id"],
            user_id=record["user_id"],
            name=record["name"],
            description=record["description"],
            created_at=record["created_at"],
            updated_at=record["updated_at"],
            role=role,
        )
