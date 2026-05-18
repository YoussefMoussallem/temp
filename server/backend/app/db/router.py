"""DB-service FE proxy router — assembler.

Mounts each domain's sub-router under one parent at ``/api/db/*``.
Cluster implementations live alongside their typed-client functions in
``app/db/<domain>.py``; this file just plumbs them together.

External consumers (``app.main``) only import ``router`` from this
module — the per-domain organisation stays an internal detail.
"""

from __future__ import annotations

from fastapi import APIRouter

from . import (
    admin,
    conversations,
    masters,
    memories,
    messages,
    projects,
    slides,
    usage,
)

router = APIRouter(tags=["db"])

# Order is presentation-only; FastAPI matches by path regardless. Usage +
# admin first so the OpenAPI listing leads with the operator-facing
# surface; CRUD endpoints follow.
router.include_router(usage.router)
router.include_router(admin.router)
router.include_router(projects.router)
router.include_router(conversations.router)
router.include_router(messages.router)
router.include_router(slides.router)
router.include_router(memories.router)
router.include_router(masters.router)
