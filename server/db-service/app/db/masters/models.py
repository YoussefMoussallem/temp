"""Master entity — typed representation of a masters table row.

A *template* in this codebase = master + theme + bundled fonts. This
row carries master + theme inside ``manifest`` (geometry, palette, font
names) and the third leg — actual font *bytes* uploaded by the user —
inside ``fonts_assets``. Each entry in ``fonts_assets`` is a dict with
``family``, ``weight``, ``style``, ``source`` (``"uploaded"`` or
``"embedded"``), ``filename``, and ``blob_url`` keys. Bytes themselves
live in Azure Blob alongside ``source_pptx_blob_url``.

The manifest column is JSONB; asyncpg returns it as ``str`` unless a
JSON codec is registered (we don't bother — the cast on read is
trivial). ``source_pptx_blob_url`` is the only place the .pptx bytes
live; we never store raw .pptx bytes in Postgres.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg


@dataclass(frozen=True)
class Master:
    id: UUID
    project_id: UUID
    name: str
    source_sha256: str | None
    manifest: dict[str, Any]
    source_pptx_blob_url: str | None
    fonts_assets: list[dict[str, Any]]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(cls, record: asyncpg.Record) -> "Master":
        manifest = record["manifest"]
        if isinstance(manifest, str):
            manifest = json.loads(manifest)
        fonts_assets = record["fonts_assets"]
        if isinstance(fonts_assets, str):
            fonts_assets = json.loads(fonts_assets)
        if fonts_assets is None:
            fonts_assets = []
        return cls(
            id=record["id"],
            project_id=record["project_id"],
            name=record["name"],
            source_sha256=record["source_sha256"],
            manifest=manifest,
            source_pptx_blob_url=record["source_pptx_blob_url"],
            fonts_assets=fonts_assets,
            created_at=record["created_at"],
            updated_at=record["updated_at"],
        )
