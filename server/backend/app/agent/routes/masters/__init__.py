"""POST /agent/masters/upload — multipart .pptx (+ optional fonts) upload.

Package layout:

  fonts.py      — font-related constants, ``_infer_font_meta``,
                  ``_build_fonts_payload`` (filename → metadata heuristics
                  and the multipart-fonts validation pipeline)
  endpoint.py   — the FastAPI route + PPTX extraction + db-service handoff

The router is defined here so ``endpoint.py`` can decorate against it
without a circular import. External code uses ``from .masters import router``
exactly as it did when this was a single file.
"""

from fastapi import APIRouter

router = APIRouter(tags=["agent"])

from . import endpoint  # noqa: F401, E402 — registers @router.post via decorator side-effect

__all__ = ["router"]
