"""Master-layouts repository — every master_layouts SQL call lives here.

Used by the masters router (POST /api/projects/{id}/masters writes
many layouts), the curation router (PATCH endpoints land in
``update_layout`` / ``set_layout_default``), and the agent appendix
(``list_layouts_by_master`` filtered to enabled=true).
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from app.db import Pool
from app.db.master_layouts import queries
from app.db.master_layouts.models import MasterLayout


async def upsert_master_layout(
    pool: Pool,
    *,
    master_id: UUID,
    master_index: int,
    layout_index: int,
    name: str,
    auto_kind: str,
    position: int,
    placeholders: list[dict[str, Any]],
    safe_area: dict[str, Any] | None,
    theme_index: int,
    font_major: str | None,
    font_minor: str | None,
    palette: dict[str, Any],
    preview_blob_url: str | None,
) -> MasterLayout:
    """Insert or refresh a single layout row.

    On conflict, the user-controlled fields (user_kind, enabled,
    is_default, position, notes) survive — re-extraction never
    clobbers user curation. ``preview_blob_url`` survives unless the
    caller passes a fresh URL (NULL means "keep").
    """
    row = await pool.fetchrow(
        queries.UPSERT,
        master_id,
        master_index,
        layout_index,
        name,
        auto_kind,
        position,
        json.dumps(placeholders),
        json.dumps(safe_area) if safe_area is not None else None,
        theme_index,
        font_major,
        font_minor,
        json.dumps(palette),
        preview_blob_url,
    )
    return MasterLayout.from_record(row)


async def get_layout(pool: Pool, layout_id: UUID) -> MasterLayout | None:
    row = await pool.fetchrow(queries.GET, layout_id)
    return MasterLayout.from_record(row) if row else None


async def list_layouts_by_master(pool: Pool, master_id: UUID) -> list[MasterLayout]:
    rows = await pool.fetch(queries.LIST_BY_MASTER, master_id)
    return [MasterLayout.from_record(r) for r in rows]


async def update_layout(
    pool: Pool,
    *,
    layout_id: UUID,
    user_kind: str | None = None,
    enabled: bool | None = None,
    position: int | None = None,
    notes: str | None = None,
    is_default: bool | None = None,
) -> MasterLayout | None:
    """Patch the user-controlled fields on a layout row.

    Each parameter follows three-state semantics: ``None`` means
    leave unchanged. ``user_kind=""`` clears the override (resolution
    falls back to auto_kind). ``notes="__CLEAR__"`` clears notes.
    Booleans pass through directly.
    """
    row = await pool.fetchrow(
        queries.UPDATE,
        layout_id,
        user_kind,
        enabled,
        position,
        notes,
        is_default,
    )
    return MasterLayout.from_record(row) if row else None


async def set_layout_default(pool: Pool, layout_id: UUID) -> MasterLayout | None:
    """Mark ``layout_id`` as the default for its (master, kind).

    Two-step transaction: clear any other layout on the same master
    that is currently default for the same kind, then set the target.
    Without the clear step, the unique partial index would reject
    the update.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            target = await conn.fetchrow(queries.GET, layout_id)
            if target is None:
                return None
            kind = target["user_kind"] or target["auto_kind"]
            await conn.execute(queries.CLEAR_DEFAULT_FOR_KIND, target["master_id"], kind)
            await conn.execute(queries.SET_DEFAULT, layout_id)
            row = await conn.fetchrow(queries.GET, layout_id)
    return MasterLayout.from_record(row) if row else None
