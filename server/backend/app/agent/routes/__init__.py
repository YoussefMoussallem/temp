"""Agent FastAPI sub-routers.

Each module under ``routes/`` defines a small ``APIRouter`` that owns one
endpoint cluster. The parent ``agent/router.py`` includes them all under
the ``/agent`` prefix.

Why split:
  * The combined surface was ~1.5k LOC in one file — hard to navigate and
    review. Per-cluster files cap each module under ~600 LOC.
  * Reduces the blast radius of edits — touching ``/masters/upload``
    can't accidentally collide with /turn changes in a diff.
  * Tests can target a single sub-router without booting the rest of the
    app surface.

Helpers used by more than one sub-router live in ``_shared.py``. Cluster-
local helpers live alongside their endpoint.
"""

from .conversations import router as conversations_router
from .export_deck import router as export_deck_router
from .masters import router as masters_router
from .memories import router as memories_router
from .meta import router as meta_router
from .turn import router as turn_router

__all__ = [
    "conversations_router",
    "export_deck_router",
    "masters_router",
    "memories_router",
    "meta_router",
    "turn_router",
]
