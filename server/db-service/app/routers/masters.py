"""Masters CRUD + activation endpoints — project-scoped templates.

Master-level routes split across two prefixes:

| Method | Path                                     | Min role |
|--------|------------------------------------------|----------|
| GET    | /api/projects/{id}/masters               | viewer   |
| POST   | /api/projects/{id}/masters               | editor   |
| GET    | /api/masters/{master_id}                 | viewer   |
| GET    | /api/masters/{master_id}/pptx            | viewer   |
| POST   | /api/masters/{master_id}/activate        | editor   |
| DELETE | /api/masters/{master_id}                 | editor   |

The split mirrors ``slides.py``: project-scoped routes for the
listing/creation and master-scoped routes for the row-level
operations. The 404-vs-403 leak is handled by
``require_project_access`` (404 when the caller has no membership at
all, 403 when they have one but lack the role).

Bytes path
----------
``POST`` accepts an optional base64-encoded .pptx. When present, we
upload to blob first, then write the row with the URL. Pure-blob
storage — no BYTEA column. The router is the only place blob writes
happen on this service so the contract stays narrow.

``GET /pptx`` streams the original .pptx by fetching from blob.
Returns 404 when the row has no associated bytes (e.g. a metadata-
only test row). Returns the application/vnd.openxml… media type so
browsers download it.
"""

from __future__ import annotations

import base64
from dataclasses import asdict
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from app.db import Pool, cache_del, cache_get_json, cache_set_json, get_pool
from app.db.master_layouts.repository import (
    get_layout,
    list_layouts_by_master,
    set_layout_default,
    update_layout,
    upsert_master_layout,
)
from app.db.masters.repository import (
    create_master,
    delete_master,
    get_active_master_id,
    get_master,
    list_masters_by_project,
    set_active_master,
)
from app.db.projects.access import require_project_access
from app.dependencies import CurrentUser, get_current_user
from app.storage import (
    delete_master_derived_assets,
    delete_master_pptx,
    fetch_master_pptx,
    is_blob_enabled,
    upload_layout_preview,
    upload_master_font,
    upload_master_pptx,
)

router = APIRouter(tags=["masters"])


# ── Schemas ──────────────────────────────────────────────────────────


class CreateMasterLayoutPayload(BaseModel):
    """One layout entry in the POST master payload.

    Mirrors the (extractor-controlled, user-controlled-omitted) shape
    that the backend's masters_upload route ships. ``preview_b64`` is
    the optional rendered PNG; when present we upload to blob and the
    row's ``preview_blob_url`` points at the result.
    """

    master_index: int
    layout_index: int
    name: str
    auto_kind: str
    position: int = 0
    placeholders: list[dict[str, Any]] = []
    safe_area: dict[str, Any] | None = None
    theme_index: int = 1
    font_major: str | None = None
    font_minor: str | None = None
    palette: dict[str, Any] = {}
    preview_b64: str | None = None


class FontAssetPayload(BaseModel):
    """One bundled brand font on a POST master payload.

    The third leg of "template = master + theme + fonts". The user
    uploads .ttf / .otf / .woff / .woff2 files alongside the .pptx;
    bytes go to Azure Blob, metadata persists on ``masters.fonts_assets``.
    """

    filename: str
    family: str
    weight: int = 400
    style: str = "normal"  # "normal" | "italic"
    bytes_b64: str
    source: str = "uploaded"  # "uploaded" | "embedded" (future)


# Allowlist of font filename extensions. Anything else is rejected
# at the router so unsigned binaries can't sneak into the blob via
# a benign-looking name.
_FONT_EXTENSIONS = {"ttf", "otf", "woff", "woff2"}

# Per-file and per-master caps. .ttf budgets vary wildly but a
# well-subset family rarely exceeds 5 MB; 25 MB total comfortably fits
# 4-6 weights without making the upload form a denial-of-service vector.
_MAX_FONT_BYTES = 5 * 1024 * 1024
_MAX_FONTS_TOTAL_BYTES = 25 * 1024 * 1024


class CreateMasterRequest(BaseModel):
    name: str
    manifest: dict[str, Any]
    source_sha256: str | None = None
    source_pptx_b64: str | None = None
    # Phase 2.3c: per-layout payloads for normalized master_layouts rows.
    # Omitted (None or empty) = legacy "manifest only" path; rows are
    # not created. Backends that have done extraction should always
    # populate this list.
    layouts: list[CreateMasterLayoutPayload] | None = None
    # Phase C: bundled brand fonts. Empty / omitted = no fonts uploaded;
    # ``masters.fonts_assets`` stays at its default ``[]``.
    fonts: list[FontAssetPayload] | None = None


class UpdateMasterLayoutRequest(BaseModel):
    """Three-state semantics align with the repository:
    * field omitted (default ``None``): leave unchanged
    * ``user_kind=""``: clear the override
    * ``notes="__CLEAR__"``: clear notes (empty-string is too easily
      sent by an empty input box; we want an explicit clear)
    """

    user_kind: str | None = None
    enabled: bool | None = None
    position: int | None = None
    notes: str | None = None


# ── Helpers ──────────────────────────────────────────────────────────


def _masters_cache_key(project_id: UUID) -> str:
    return f"cache:project:{project_id}:masters"


def _serialize(master) -> dict:
    """Dataclass → JSON-friendly dict. asdict() doesn't know how to
    handle UUIDs or datetimes; we coerce to str/isoformat here."""
    d = asdict(master)
    for k, v in d.items():
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
        elif isinstance(v, UUID):
            d[k] = str(v)
    return d


async def _persist_fonts(
    *,
    project_id: UUID,
    sha256: str | None,
    fonts: list[FontAssetPayload] | None,
) -> list[dict[str, Any]]:
    """Validate, decode, and upload each bundled font; return the list
    of metadata dicts ready for ``masters.fonts_assets``.

    Returns ``[]`` when no fonts are attached. Raises ``HTTPException``
    on any per-font validation failure (bad base64, bad extension,
    payload too large) — the router's ``ON CONFLICT`` upsert will leave
    the existing row unchanged so a partial upload doesn't half-overwrite.
    """
    if not fonts:
        return []
    if not is_blob_enabled():
        raise HTTPException(
            status_code=503,
            detail="Blob storage not configured for font uploads.",
        )
    if not sha256:
        # Same reasoning as layout previews — the blob path is keyed
        # on source SHA so re-uploading the same template overwrites
        # in place. Without a SHA we'd write to a synthetic path that
        # never collides on re-upload.
        raise HTTPException(
            status_code=400,
            detail="source_sha256 required when fonts are attached",
        )

    persisted: list[dict[str, Any]] = []
    total_bytes = 0
    for font in fonts:
        ext = font.filename.rsplit(".", 1)[-1].lower() if "." in font.filename else ""
        if ext not in _FONT_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"font {font.filename!r}: extension must be one of {sorted(_FONT_EXTENSIONS)}"
                ),
            )
        if "/" in font.filename or "\\" in font.filename:
            raise HTTPException(
                status_code=400,
                detail=f"font {font.filename!r}: filename must not contain path separators",
            )
        try:
            data = base64.b64decode(font.bytes_b64, validate=True)
        except Exception:
            raise HTTPException(
                status_code=400,
                detail=f"font {font.filename!r}: bytes_b64 is not valid base64",
            )
        if len(data) > _MAX_FONT_BYTES:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"font {font.filename!r}: {len(data)} bytes exceeds "
                    f"{_MAX_FONT_BYTES}-byte per-file cap"
                ),
            )
        total_bytes += len(data)
        if total_bytes > _MAX_FONTS_TOTAL_BYTES:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"total font payload exceeds {_MAX_FONTS_TOTAL_BYTES}-byte cap "
                    f"(stopped at {font.filename!r})"
                ),
            )
        if font.weight < 100 or font.weight > 900:
            raise HTTPException(
                status_code=400,
                detail=f"font {font.filename!r}: weight must be 100..900",
            )
        if font.style not in {"normal", "italic"}:
            raise HTTPException(
                status_code=400,
                detail=f"font {font.filename!r}: style must be 'normal' or 'italic'",
            )

        blob_url = await upload_master_font(
            project_id=str(project_id),
            sha256=sha256,
            filename=font.filename,
            data=data,
        )
        persisted.append(
            {
                "filename": font.filename,
                "family": font.family,
                "weight": font.weight,
                "style": font.style,
                "source": font.source,
                "blob_url": blob_url,
            }
        )

    return persisted


async def _require_master_access(pool: Pool, master_id: UUID, user: CurrentUser, *, min_role: str):
    """Look up the master, then enforce the caller's role on its
    parent project. Returns the master row to avoid a second fetch
    in the handler."""
    master = await get_master(pool, master_id)
    if master is None:
        raise HTTPException(status_code=404, detail="Master not found")
    await require_project_access(pool, master.project_id, user, min_role=min_role)
    return master


# ── Project-scoped routes ────────────────────────────────────────────


@router.get("/projects/{project_id}/masters")
async def list_masters(
    project_id: UUID,
    user: CurrentUser = Depends(get_current_user),
):
    """Return every master in the project, plus the project's
    ``active_master_id`` so the FE can render the 'active' pill on
    the right card without a second round-trip.

    The cache holds only the (potentially large) masters list; the
    active pointer is a one-row Postgres lookup that's cheaper than
    a Redis round-trip, so we always read it fresh. This also avoids
    a stale-pointer class of bug where Redis remembers an old active
    after the user re-imported the same template.
    """
    pool: Pool = await get_pool()
    await require_project_access(pool, project_id, user, min_role="viewer")

    active_id = await get_active_master_id(pool, project_id)

    key = _masters_cache_key(project_id)
    cached = await cache_get_json(key)
    if cached is not None:
        return {
            "masters": cached,
            "active_master_id": str(active_id) if active_id else None,
        }

    masters = await list_masters_by_project(pool, project_id)
    payload = [_serialize(m) for m in masters]
    cache_set_json(key, payload)
    return {
        "masters": payload,
        "active_master_id": str(active_id) if active_id else None,
    }


@router.post("/projects/{project_id}/masters")
async def create(
    project_id: UUID,
    body: CreateMasterRequest,
    user: CurrentUser = Depends(get_current_user),
):
    pool: Pool = await get_pool()
    await require_project_access(pool, project_id, user, min_role="editor")

    blob_url: str | None = None
    if body.source_pptx_b64:
        try:
            data = base64.b64decode(body.source_pptx_b64, validate=True)
        except Exception:
            raise HTTPException(status_code=400, detail="source_pptx_b64 is not valid base64")
        if not is_blob_enabled():
            # Hard fail: when bytes arrive but no blob is configured,
            # we'd lose them silently. Better to tell the caller.
            raise HTTPException(
                status_code=503,
                detail=(
                    "Blob storage not configured. Set "
                    "AZURE_BLOB_CONNECTION_STRING (Azurite) or "
                    "AZURE_BLOB_ACCOUNT_URL (cloud) on db-service."
                ),
            )
        # SHA-keyed path so a re-upload of the exact same file lands
        # on the same blob — matches the Postgres ON CONFLICT behaviour.
        blob_url = await upload_master_pptx(
            project_id=str(project_id),
            master_id="pending",  # only used as fallback when sha is None
            sha256=body.source_sha256,
            data=data,
        )

    # Phase C: process bundled fonts. Each goes to blob;
    # ``masters.fonts_assets`` stores the resolved metadata.
    fonts_assets = await _persist_fonts(
        project_id=project_id,
        sha256=body.source_sha256,
        fonts=body.fonts,
    )

    master = await create_master(
        pool,
        project_id=project_id,
        name=body.name,
        manifest=body.manifest,
        source_sha256=body.source_sha256,
        source_pptx_blob_url=blob_url,
        fonts_assets=fonts_assets,
    )

    # Phase 2.3c: persist per-layout rows + upload preview PNGs.
    if body.layouts:
        for layout in body.layouts:
            preview_url: str | None = None
            if layout.preview_b64:
                if not is_blob_enabled():
                    # Same hard-fail policy as source bytes — we never
                    # silently drop user data.
                    raise HTTPException(
                        status_code=503,
                        detail="Blob storage not configured for layout previews.",
                    )
                if not body.source_sha256:
                    # Preview blob path is keyed on source_sha256 for
                    # cache stability. Without it we'd write to a
                    # synthetic path that never collides on re-upload —
                    # acceptable for tests, but reject in production
                    # to keep the contract narrow.
                    raise HTTPException(
                        status_code=400,
                        detail="source_sha256 required when preview_b64 is set",
                    )
                try:
                    png_bytes = base64.b64decode(layout.preview_b64, validate=True)
                except Exception:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"layout (m={layout.master_index}, "
                            f"l={layout.layout_index}): preview_b64 invalid base64"
                        ),
                    )
                preview_url = await upload_layout_preview(
                    project_id=str(project_id),
                    sha256=body.source_sha256,
                    master_index=layout.master_index,
                    layout_index=layout.layout_index,
                    data=png_bytes,
                )

            await upsert_master_layout(
                pool,
                master_id=master.id,
                master_index=layout.master_index,
                layout_index=layout.layout_index,
                name=layout.name,
                auto_kind=layout.auto_kind,
                position=layout.position,
                placeholders=layout.placeholders,
                safe_area=layout.safe_area,
                theme_index=layout.theme_index,
                font_major=layout.font_major,
                font_minor=layout.font_minor,
                palette=layout.palette,
                preview_blob_url=preview_url,
            )

    cache_del(_masters_cache_key(project_id))
    return _serialize(master)


# ── Layout-scoped routes (curation UI) ───────────────────────────────


def _serialize_layout(row) -> dict:
    """Same coercions as ``_serialize`` for masters, but on
    MasterLayout. Kept separate because field sets differ enough that
    a generic helper would obscure intent."""
    d = asdict(row)
    for k, v in d.items():
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
        elif isinstance(v, UUID):
            d[k] = str(v)
    return d


@router.get("/masters/{master_id}/layouts")
async def list_layouts(
    master_id: UUID,
    user: CurrentUser = Depends(get_current_user),
):
    """Return every layout row for a master, ordered by ``position``.

    Used by the curation UI to render the grid and by the agent
    appendix (filtered to ``enabled=TRUE`` server-side via the
    indexed view; today the FE filters in memory but the index is
    in place for when the appendix moves over).
    """
    pool: Pool = await get_pool()
    master = await _require_master_access(pool, master_id, user, min_role="viewer")
    rows = await list_layouts_by_master(pool, master.id)
    return {"layouts": [_serialize_layout(r) for r in rows]}


@router.patch("/master_layouts/{layout_id}")
async def patch_layout(
    layout_id: UUID,
    body: UpdateMasterLayoutRequest,
    user: CurrentUser = Depends(get_current_user),
):
    """PATCH the user-controlled fields of a layout row.

    Authorisation flows through the parent master's project access
    check — we never expose layouts as a free-standing resource. ``editor``
    role required because curation changes affect every subsequent slide
    generation.
    """
    pool: Pool = await get_pool()
    layout = await get_layout(pool, layout_id)
    if layout is None:
        raise HTTPException(status_code=404, detail="Layout not found")
    master = await get_master(pool, layout.master_id)
    if master is None:
        raise HTTPException(status_code=404, detail="Layout not found")
    await require_project_access(pool, master.project_id, user, min_role="editor")

    updated = await update_layout(
        pool,
        layout_id=layout_id,
        user_kind=body.user_kind,
        enabled=body.enabled,
        position=body.position,
        notes=body.notes,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Layout not found")
    cache_del(_masters_cache_key(master.project_id))
    return _serialize_layout(updated)


@router.post("/master_layouts/{layout_id}/default")
async def post_layout_default(
    layout_id: UUID,
    user: CurrentUser = Depends(get_current_user),
):
    """Mark a layout as the default for its (master, kind).

    The repository runs the clear-others-then-set in a single
    transaction so the unique partial index never fires mid-call.
    """
    pool: Pool = await get_pool()
    layout = await get_layout(pool, layout_id)
    if layout is None:
        raise HTTPException(status_code=404, detail="Layout not found")
    master = await get_master(pool, layout.master_id)
    if master is None:
        raise HTTPException(status_code=404, detail="Layout not found")
    await require_project_access(pool, master.project_id, user, min_role="editor")

    updated = await set_layout_default(pool, layout_id=layout_id)
    if updated is None:
        raise HTTPException(status_code=404, detail="Layout not found")
    cache_del(_masters_cache_key(master.project_id))
    return _serialize_layout(updated)


# ── Master-scoped routes ─────────────────────────────────────────────


@router.get("/masters/{master_id}")
async def get(
    master_id: UUID,
    user: CurrentUser = Depends(get_current_user),
):
    pool: Pool = await get_pool()
    master = await _require_master_access(pool, master_id, user, min_role="viewer")
    return _serialize(master)


@router.get("/masters/{master_id}/pptx")
async def get_pptx(
    master_id: UUID,
    user: CurrentUser = Depends(get_current_user),
):
    """Stream the original .pptx bytes for export-time inheritance.

    404 distinguishes "no master with that id" (handled by access
    helper) from "master row exists but never had bytes" (returned
    here). The latter happens for metadata-only rows used in tests.
    """
    pool: Pool = await get_pool()
    master = await _require_master_access(pool, master_id, user, min_role="viewer")
    if not master.source_pptx_blob_url:
        raise HTTPException(status_code=404, detail="Master has no stored PPTX")

    data = await fetch_master_pptx(master.source_pptx_blob_url)
    return Response(
        content=data,
        media_type=("application/vnd.openxmlformats-officedocument.presentationml.presentation"),
    )


@router.post("/masters/{master_id}/activate")
async def activate(
    master_id: UUID,
    user: CurrentUser = Depends(get_current_user),
):
    """Set ``projects.active_master_id`` to this master.

    Editor role required because activating a different master
    changes how every subsequent slide is generated — that's a deck-
    altering operation, not a read.
    """
    pool: Pool = await get_pool()
    master = await _require_master_access(pool, master_id, user, min_role="editor")
    await set_active_master(pool, master.project_id, master.id)
    cache_del(_masters_cache_key(master.project_id))
    return {"project_id": str(master.project_id), "active_master_id": str(master.id)}


@router.delete("/masters/{master_id}", status_code=204)
async def delete(
    master_id: UUID,
    user: CurrentUser = Depends(get_current_user),
):
    """Delete the row and its blobs. ``projects.active_master_id``
    self-clears via ON DELETE SET NULL, so we don't have to manage it.

    Blob deletion is best-effort: an orphaned blob is annoying but
    not fatal. Sweeps three locations:

    * ``source_pptx_blob_url`` — the original .pptx
    * ``{project_id}/{sha256}/layouts/`` — layout preview PNGs
    * ``{project_id}/{sha256}/fonts/`` — bundled brand fonts (Phase C)

    The derived-asset sweep keys on the SHA, so re-uploading the same
    template after a delete starts from a clean slate."""
    pool: Pool = await get_pool()
    master = await _require_master_access(pool, master_id, user, min_role="editor")

    if is_blob_enabled():
        if master.source_pptx_blob_url:
            await delete_master_pptx(master.source_pptx_blob_url)
        if master.source_sha256:
            await delete_master_derived_assets(
                str(master.project_id),
                master.source_sha256,
            )

    await delete_master(pool, master_id)
    cache_del(_masters_cache_key(master.project_id))
    return None
