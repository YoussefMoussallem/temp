"""Master repository — every masters table SQL call lives here.

The router and the agent's bridge layer call into this module; nothing
else does. Bytes are NOT stored here — callers upload to blob first
and pass the URL in. The repo is unaware of Azurite vs cloud blob.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from app.db import Pool
from app.db.masters import queries
from app.db.masters.models import Master


async def create_master(
    pool: Pool,
    *,
    project_id: UUID,
    name: str,
    manifest: dict[str, Any],
    source_sha256: str | None = None,
    source_pptx_blob_url: str | None = None,
    fonts_assets: list[dict[str, Any]] | None = None,
) -> Master:
    """Insert (or upsert on SHA) a master row.

    Re-uploading a template with the same SHA is idempotent — the row
    keeps its id and we refresh ``name``, ``manifest``,
    ``source_pptx_blob_url``, and ``fonts_assets``. Callers don't need
    to check for existence first.

    ``fonts_assets`` defaults to an empty list when omitted; pass
    ``[{family, weight, style, source, filename, blob_url}, ...]`` to
    register uploaded brand fonts alongside the .pptx.
    """
    row = await pool.fetchrow(
        queries.INSERT,
        project_id,
        name,
        source_sha256,
        json.dumps(manifest),
        source_pptx_blob_url,
        json.dumps(fonts_assets or []),
    )
    return Master.from_record(row)


async def get_master(pool: Pool, master_id: UUID) -> Master | None:
    row = await pool.fetchrow(queries.GET, master_id)
    return Master.from_record(row) if row else None


async def list_masters_by_project(pool: Pool, project_id: UUID) -> list[Master]:
    rows = await pool.fetch(queries.LIST_BY_PROJECT, project_id)
    return [Master.from_record(r) for r in rows]


async def delete_master(pool: Pool, master_id: UUID) -> None:
    """Remove the row. ``projects.active_master_id`` clears via
    ON DELETE SET NULL, so we don't have to manage it here."""
    await pool.execute(queries.DELETE, master_id)


async def set_active_master(pool: Pool, project_id: UUID, master_id: UUID | None) -> None:
    """Point a project at a master (or clear the pointer with ``None``).

    Validation of the master existing / belonging to the project is
    the caller's responsibility — at the router layer we know the
    request context, here we just mutate.
    """
    await pool.execute(queries.SET_ACTIVE, project_id, master_id)


async def get_active_master_id(pool: Pool, project_id: UUID) -> UUID | None:
    """Read the project's currently-active master, or ``None``.

    Cheap single-row lookup — the projects table indexes on id. We
    surface this alongside the masters list so the FE can pin the
    'active' pill on the right card after a page navigation.
    """
    row = await pool.fetchrow(queries.GET_ACTIVE_FOR_PROJECT, project_id)
    return row["active_master_id"] if row else None
