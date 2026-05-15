"""MasterLayout entity — typed representation of a master_layouts row.

The same JSON-coercion-on-read pattern as Master/Slide: asyncpg gives
us either a dict or a string depending on whether a JSONB codec is
registered, so we coerce defensively.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg


def _coerce_jsonb(value: Any) -> Any:
    """asyncpg returns JSONB as a str unless a codec is registered.
    Callers expect dicts/lists; coerce here so each repo doesn't repeat
    the same defensive parse."""
    if isinstance(value, (str, bytes)):
        return json.loads(value)
    return value


@dataclass(frozen=True)
class MasterLayout:
    id: UUID
    master_id: UUID
    master_index: int
    layout_index: int
    name: str
    auto_kind: str
    user_kind: str | None
    enabled: bool
    is_default: bool
    position: int
    notes: str | None
    preview_blob_url: str | None
    placeholders: list[dict[str, Any]]
    safe_area: dict[str, Any] | None
    theme_index: int
    font_major: str | None
    font_minor: str | None
    palette: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    @property
    def kind(self) -> str:
        """Effective kind: user override wins over auto-classification.
        The agent appendix and the curation UI always read this."""
        return self.user_kind or self.auto_kind

    @classmethod
    def from_record(cls, record: asyncpg.Record) -> "MasterLayout":
        return cls(
            id=record["id"],
            master_id=record["master_id"],
            master_index=record["master_index"],
            layout_index=record["layout_index"],
            name=record["name"],
            auto_kind=record["auto_kind"],
            user_kind=record["user_kind"],
            enabled=record["enabled"],
            is_default=record["is_default"],
            position=record["position"],
            notes=record["notes"],
            preview_blob_url=record["preview_blob_url"],
            placeholders=_coerce_jsonb(record["placeholders"]),
            safe_area=_coerce_jsonb(record["safe_area"]),
            theme_index=record["theme_index"],
            font_major=record["font_major"],
            font_minor=record["font_minor"],
            palette=_coerce_jsonb(record["palette"]),
            created_at=record["created_at"],
            updated_at=record["updated_at"],
        )
