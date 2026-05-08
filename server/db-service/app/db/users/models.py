"""User entity model — typed representation of a users table row."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import asyncpg


@dataclass(frozen=True)
class User:
    azure_oid: str
    email: str
    display_name: str | None
    created_at: datetime

    @classmethod
    def from_record(cls, record: asyncpg.Record) -> User:
        return cls(
            azure_oid=record["azure_oid"],
            email=record["email"],
            display_name=record["display_name"],
            created_at=record["created_at"],
        )
