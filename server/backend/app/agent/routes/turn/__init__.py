"""POST /agent/turn — the agentic loop endpoint.

Package layout:

  schemas.py   — request models (AgentTurnRequest, ToolResultPayload, ImagePayload)
  helpers.py   — message-shape + persistence helpers (turn-local)
  messages.py  — _build_turn_messages + result dataclasses (the pre-loop
                 wrangling that produces the message list the loop runs on)
  endpoint.py  — the FastAPI route + the _stream_turn SSE generator

The router is defined here so `endpoint.py` can decorate against it
without a circular import; importing ``endpoint`` for its side effects
registers the route. External code uses ``from .turn import router``
exactly as it did when this was a single file.
"""

from fastapi import APIRouter

router = APIRouter(tags=["agent"])

# Importing endpoint registers @router.post("/turn") via decorator
# side-effect. Keep the import below the router definition.
from . import endpoint  # noqa: F401, E402

__all__ = ["router"]
