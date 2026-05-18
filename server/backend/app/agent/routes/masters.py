"""POST /agent/masters/upload — frontend file picker for the Master Manager.

Multipart entry point so a 5–100 MB .pptx doesn't have to round-trip
through the LLM as base64 in a tool call. Flow:

  FE picker → multipart POST here → extract manifest from bytes →
  forward {manifest, sha, b64} to db-service → db-service uploads
  bytes to blob and writes the row

We extract on the backend (not db-service) because slide_ir lives
here — the extractor depends on python-pptx + lxml which are heavy
imports we'd rather not pay for in db-service.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from app.bridges import db_client
from app.dependencies import CurrentUser, get_current_user
from app.middleware.rate_limit import limiter, user_or_ip_key
from app_logger import get_logger

if TYPE_CHECKING:
    from pptx_master import LayoutDescriptor

log = get_logger(__name__)

router = APIRouter(tags=["agent"])


# Bytes go to Azure Blob, not Postgres BYTEA, so the practical ceiling
# is the LLM's appetite for re-extracting the manifest each turn (it's
# cheap — JSON is small). 100 MB covers heavily-illustrated corporate
# templates. Sized to match the ImportMasterTool guard.
_MAX_MASTER_UPLOAD_BYTES = 100 * 1024 * 1024


# Phase C — bundled brand fonts. The user uploads .ttf/.otf alongside
# the .pptx; we infer family/weight/style from the filename so the FE
# never has to ask. db-service caps per-file (5 MB) and total (25 MB)
# size; matching the per-file cap here prevents wasting a multipart
# parse on a font we'd reject downstream.
_MAX_FONT_BYTES = 5 * 1024 * 1024
_FONT_EXTENSIONS = {"ttf", "otf", "woff", "woff2"}

# Lower-case stem suffix → CSS weight number. Order matters when a
# longer name contains a shorter one (``ExtraBold`` would otherwise
# match ``Bold``); we look up by the longest hit, see _infer_font_meta.
_WEIGHT_TOKENS: dict[str, int] = {
    "thin": 100,
    "hairline": 100,
    "ultralight": 200,
    "extralight": 200,
    "light": 300,
    "book": 400,
    "regular": 400,
    "normal": 400,
    "medium": 500,
    "semibold": 600,
    "demibold": 600,
    "bold": 700,
    "extrabold": 800,
    "ultrabold": 800,
    "heavy": 900,
    "black": 900,
}


def _infer_font_meta(filename: str) -> dict:
    """Heuristically pull ``family``, ``weight``, ``style`` from a font
    filename like ``STCForward-Bold.ttf`` or ``Fund-LightItalic.ttf``.

    Algorithm:
    1. Strip extension.
    2. Lower-case-search for the longest weight-token match; remove it.
    3. Lower-case-search for ``italic`` / ``oblique``; remove it.
    4. Split on ``-`` / ``_`` and reassemble with spaces — that's the
       family. Empty fallbacks → original stem.

    Heuristics are best-effort. If a vendor uses a different naming
    convention the worst case is weight 400 / style normal — the
    consumption side will still find the file by family + filename.
    """
    stem = filename.rsplit(".", 1)[0]
    lower = stem.lower()

    weight = 400
    matched_token: str | None = None
    for token in sorted(_WEIGHT_TOKENS, key=len, reverse=True):
        if token in lower:
            weight = _WEIGHT_TOKENS[token]
            matched_token = token
            break

    style = "normal"
    if "italic" in lower or "oblique" in lower:
        style = "italic"

    cleaned = lower
    if matched_token:
        cleaned = cleaned.replace(matched_token, "")
    cleaned = cleaned.replace("italic", "").replace("oblique", "")
    # Split on common delimiters and drop empties.
    pieces = [p.strip() for sep in ("-", "_") for p in cleaned.replace(" ", sep).split(sep)]
    family_raw = " ".join(p for p in pieces if p) or stem
    # Title-case the family — "stcforward" → "Stcforward" reads worse
    # than the original mixed case, so we re-derive from the original
    # stem when our cleaned slug looks fine.
    family = family_raw.strip().title()
    return {"family": family, "weight": weight, "style": style}


async def _build_fonts_payload(font_uploads: list) -> list[dict]:
    """Read each multipart font file, validate, base64-encode, and
    return the list ready for ``db_client.create_master(fonts=...)``.

    Validation rejects empty files, oversized files, and disallowed
    extensions early (saving a round-trip to db-service). Filename
    metadata is inferred via ``_infer_font_meta`` so the FE only has
    to upload the file.
    """
    import base64 as _b64  # noqa: PLC0415

    payload: list[dict] = []
    for f in font_uploads:
        if not hasattr(f, "read"):
            continue
        font_filename = getattr(f, "filename", "") or ""
        if not font_filename:
            raise HTTPException(
                status_code=400,
                detail="font upload missing filename",
            )
        ext = font_filename.rsplit(".", 1)[-1].lower() if "." in font_filename else ""
        if ext not in _FONT_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"font {font_filename!r}: extension must be one of {sorted(_FONT_EXTENSIONS)}"
                ),
            )
        if "/" in font_filename or "\\" in font_filename:
            raise HTTPException(
                status_code=400,
                detail=f"font {font_filename!r}: filename must not contain path separators",
            )

        font_bytes = await f.read()
        if not font_bytes:
            raise HTTPException(
                status_code=400,
                detail=f"font {font_filename!r}: empty file",
            )
        if len(font_bytes) > _MAX_FONT_BYTES:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"font {font_filename!r}: {len(font_bytes)} bytes exceeds "
                    f"{_MAX_FONT_BYTES}-byte cap"
                ),
            )

        meta = _infer_font_meta(font_filename)
        payload.append(
            {
                "filename": font_filename,
                "family": meta["family"],
                "weight": meta["weight"],
                "style": meta["style"],
                "bytes_b64": _b64.b64encode(font_bytes).decode("ascii"),
                "source": "uploaded",
            }
        )

    return payload


@router.post("/masters/upload")
@limiter.limit("10/minute", key_func=user_or_ip_key)
async def masters_upload(
    request: Request,
    authorization: str | None = Header(default=None),
    user: CurrentUser = Depends(get_current_user),
):
    """Upload a .pptx as a project master.

    Multipart form fields:
      * ``file`` — the .pptx (or .potx) bytes
      * ``project_id`` — UUID of the parent project
      * ``name`` (optional) — display label; falls back to the PPTX
        core-properties title or 'Imported master'

    Returns ``{"master": <row>, "summary": <manifest summary>}`` so
    the FE can drop the row into local state without a refetch.
    Idempotent on (project_id, source_sha256): re-uploading the same
    .pptx into the same project refreshes the existing row.
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    form = await request.form()
    upload = form.get("file")
    project_id = (form.get("project_id") or "").strip()
    name = (form.get("name") or "").strip() or None
    # Phase C: optional bundled brand fonts. Each font posted as a
    # repeated form field named ``fonts``. We infer family/weight/style
    # from the filename below — the FE never has to compute it.
    font_uploads = form.getlist("fonts")

    if not project_id:
        raise HTTPException(status_code=400, detail="project_id is required")
    if upload is None or not hasattr(upload, "read"):
        raise HTTPException(status_code=400, detail="file is required")

    # Keep the original casing for fallback naming below; only lowercase
    # the suffix-check copy.
    filename_raw = getattr(upload, "filename", "") or ""
    filename = filename_raw.lower()
    if not (filename.endswith(".pptx") or filename.endswith(".potx")):
        raise HTTPException(status_code=400, detail="Expected a .pptx or .potx upload")

    data = await upload.read()
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    if len(data) > _MAX_MASTER_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(f"File too large ({len(data)} bytes); limit is {_MAX_MASTER_UPLOAD_BYTES}."),
        )

    # Deferred imports keep the route cheap on cold start when no
    # one has uploaded yet — extracting pulls python-pptx + lxml
    # (~30MB working memory).
    import base64  # noqa: PLC0415

    from pptx_master import extract_master_from_pptx  # noqa: PLC0415
    from app.services.pptx_renderer import PptxRenderer  # noqa: PLC0415

    try:
        manifest = extract_master_from_pptx(data, name=name)
    except Exception as e:  # noqa: BLE001
        log.exception("masters_upload: failed to parse PPTX")
        raise HTTPException(status_code=422, detail=f"Failed to parse PPTX: {e}") from e

    # Fall back to the upload's filename when extraction yielded the
    # generic default. Two masters that were both extracted to
    # ``"Imported master"`` are indistinguishable in the curation list,
    # which has bitten users (wrong-master activations). The filename
    # is the most discriminating bit of metadata available without
    # hitting the .pptx core props (which were already empty if we got
    # here).
    # PowerPoint's default core-property titles aren't useful as master
    # names — every blank-deck-saved-as-template ships with one of these
    # literal strings. Treat them as "no real title" and prefer the
    # upload's filename so users can tell their masters apart.
    _DEFAULT_PPTX_TITLES = {
        "Imported master",
        "PowerPoint Presentation",
        "Untitled",
        "Presentation1",
        "Slide Show",
        "Slide1",
    }
    if manifest.name in _DEFAULT_PPTX_TITLES and filename_raw:
        from pathlib import Path  # noqa: PLC0415

        manifest.name = Path(filename_raw).stem or manifest.name

    # Build the flat list of (master_index, layout_index) pairs for both
    # the renderer and the db-service payload. Walk masters[] when present
    # (Phase 2.1+); fall back to the legacy single-master ``layouts`` for
    # back-compat with any synthetic fixture that still uses it.
    if manifest.masters:
        flat_layouts: list[tuple[int, int, "LayoutDescriptor"]] = [
            (m.index, idx, lay) for m in manifest.masters for idx, lay in enumerate(m.layouts)
        ]
        master_palettes: dict[int, dict] = {m.index: dict(m.palette) for m in manifest.masters}
        master_fonts: dict[int, dict] = {m.index: dict(m.fonts) for m in manifest.masters}
        master_theme_idx: dict[int, int] = {m.index: m.theme_index for m in manifest.masters}
    else:
        flat_layouts = [(lay.master_index, idx, lay) for idx, lay in enumerate(manifest.layouts)]
        master_palettes = {0: dict(manifest.theme.colors)}
        master_fonts = {0: dict(manifest.theme.fonts)}
        master_theme_idx = {0: 1}

    # Best-effort: render previews via the sidecar. Failures (sidecar
    # unreachable, timeout, etc.) demote to "no previews" — the master
    # is still importable, the FE just shows placeholder cards.
    specs = [(m_idx, lay.layout_index) for m_idx, _pos, lay in flat_layouts]
    previews: dict[tuple[int, int], bytes] = {}
    try:
        previews = await PptxRenderer().render_layouts(data, specs)
        log.info(
            "masters_upload: rendered %d / %d layout previews",
            len(previews),
            len(specs),
        )
    except Exception:  # noqa: BLE001
        log.warning("masters_upload: layout preview rendering failed", exc_info=True)
        previews = {}

    layouts_payload: list[dict] = []
    for m_idx, position, lay in flat_layouts:
        png = previews.get((m_idx, lay.layout_index))
        layouts_payload.append(
            {
                "master_index": m_idx,
                "layout_index": lay.layout_index,
                "name": lay.name,
                "auto_kind": lay.kind,
                "position": position,
                "placeholders": [p.model_dump() for p in lay.placeholders],
                "safe_area": lay.safe_area.model_dump() if lay.safe_area else None,
                "theme_index": master_theme_idx.get(m_idx, 1),
                "font_major": master_fonts.get(m_idx, {}).get("major"),
                "font_minor": master_fonts.get(m_idx, {}).get("minor"),
                "palette": master_palettes.get(m_idx, {}),
                "preview_b64": (base64.b64encode(png).decode("ascii") if png else None),
            }
        )

    fonts_payload = await _build_fonts_payload(font_uploads)

    try:
        master = await db_client.create_master(
            authorization,
            project_id,
            name=manifest.name,
            manifest=manifest.model_dump(),
            source_sha256=manifest.source_sha256,
            source_pptx_b64=base64.b64encode(data).decode("ascii"),
            layouts=layouts_payload,
            fonts=fonts_payload or None,
        )
    except Exception as e:  # noqa: BLE001
        log.exception("masters_upload: db-service create_master failed")
        raise HTTPException(status_code=502, detail="Failed to persist master") from e

    return {
        "master": master,
        "summary": {
            "name": manifest.name,
            "canvas": manifest.canvas.model_dump(),
            "fonts": manifest.theme.fonts,
            "primary_color": manifest.theme.colors.get("primary"),
            "safe_area": manifest.safe_area.model_dump(),
            "chrome_elements": len(manifest.chrome),
            "layouts": [{"name": layout.name, "kind": layout.kind} for layout in manifest.layouts],
        },
    }
