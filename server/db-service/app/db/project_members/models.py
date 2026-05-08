"""Project member entity — typed representation of a project_members row.

Two dataclasses live here:

- ``ProjectMember`` — the raw row (user_id, project_id, role, joined_at).
  Used for write paths (insert / update / delete) where we don't need the
  invitee's display info.
- ``MemberView`` — a row joined with ``users`` so the UI can render
  "Alice <alice@pwc.com> — editor" without a second round-trip. Used by
  ``GET /projects/{id}/members``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import asyncpg


@dataclass(frozen=True)
class ProjectMember:
    user_id: str
    project_id: UUID
    role: str
    joined_at: datetime

    @classmethod
    def from_record(cls, record: asyncpg.Record) -> ProjectMember:
        return cls(
            user_id=record["user_id"],
            project_id=record["project_id"],
            role=record["role"],
            joined_at=record["joined_at"],
        )


@dataclass(frozen=True)
class MemberView:
    """Project member joined with users — used by member-list endpoints."""

    user_id: str
    project_id: UUID
    role: str
    joined_at: datetime
    email: str
    display_name: str | None

    @classmethod
    def from_record(cls, record: asyncpg.Record) -> MemberView:
        return cls(
            user_id=record["user_id"],
            project_id=record["project_id"],
            role=record["role"],
            joined_at=record["joined_at"],
            email=record["email"],
            display_name=record["display_name"],
        )
