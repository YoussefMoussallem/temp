"""Font filename heuristics + multipart-fonts validation pipeline.

Used by ``endpoint.py`` when a master upload includes bundled brand
fonts. The pure ``_infer_font_meta`` helper is also imported by
``tests/test_font_meta.py`` so the inference behaviour is regression-
checked independently of the upload route.
"""

from __future__ import annotations

from fastapi import HTTPException


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
