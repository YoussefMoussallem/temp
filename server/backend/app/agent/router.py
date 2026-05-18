"""Agent FastAPI router — assembler.

Single parent ``APIRouter`` mounted at ``/agent`` that includes one sub-
router per endpoint cluster. Cluster implementations live under
``routes/``:

  * ``routes/turn.py``           — POST /turn (the agentic loop)
  * ``routes/export_deck.py``    — POST /export-deck (button-driven .pptx)
  * ``routes/conversations.py``  — POST /conversations/{id}/generate-title
  * ``routes/memories.py``       — POST /memories/from-text (UI-driven memory)
  * ``routes/masters.py``        — POST /masters/upload (multipart .pptx upload)
  * ``routes/meta.py``           — GET  /skills, /models, /commands;
                                    POST /compact, /context, /usage (stubs)

External consumers (``app.main``, tests) only import ``router`` from
this module — the sub-router structure stays an internal organisational
detail.
"""

from __future__ import annotations

from fastapi import APIRouter

from .routes import (
    conversations_router,
    export_deck_router,
    masters_router,
    memories_router,
    meta_router,
    turn_router,
)

router = APIRouter(prefix="/agent", tags=["agent"])

# Order is presentation-only — FastAPI matches by path regardless. We
# keep the heaviest cluster (/turn) first so the OpenAPI listing leads
# with the primary surface.
router.include_router(turn_router)
router.include_router(export_deck_router)
router.include_router(conversations_router)
router.include_router(memories_router)
router.include_router(masters_router)
router.include_router(meta_router)
