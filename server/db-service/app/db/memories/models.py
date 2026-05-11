"""Memory entities — typed representations of memory table rows.

Two row types for two scopes. They share a common shape but differ in
their owning key (``user_id`` vs ``project_id``) and whether they carry
an audit field (``created_by_user_id`` on project memories). Keeping
them as separate dataclasses — instead of one with optional fields —
makes scope-related bugs surface at the type boundary rather than at
runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import asyncpg


@dataclass(frozen=True)
class UserMemory:
    id: UUID
    user_id: str
    slug: str
    type: str
    name: str
    description: str
    body: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(cls, record: asyncpg.Record) -> UserMemory:
        return cls(
            id=record["id"],
            user_id=record["user_id"],
            slug=record["slug"],
            type=record["type"],
            name=record["name"],
            description=record["description"],
            body=record["body"],
            created_at=record["created_at"],
            updated_at=record["updated_at"],
        )


@dataclass(frozen=True)
class ProjectMemory:
    id: UUID
    project_id: UUID
    slug: str
    type: str
    name: str
    description: str
    body: str
    created_by_user_id: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(cls, record: asyncpg.Record) -> ProjectMemory:
        return cls(
            id=record["id"],
            project_id=record["project_id"],
            slug=record["slug"],
            type=record["type"],
            name=record["name"],
            description=record["description"],
            body=record["body"],
            created_by_user_id=record["created_by_user_id"],
            created_at=record["created_at"],
            updated_at=record["updated_at"],
        )
