"""Shared helpers for the agent FastAPI route modules.

Only contains helpers used by **more than one** sub-router. Cluster-local
helpers live alongside their endpoint in the relevant ``routes/*.py``
module — keeps the import graph honest and prevents this file from
turning into a kitchen-sink ``utils.py``.

Today: only the SSE event formatter ``_sse`` (used by both ``/turn`` and
``/export-deck``) and its JSON serializer helper.
"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from typing import Any


def _json_default(obj: Any) -> Any:
    """JSON serializer for dataclasses + other non-serializable types."""
    if is_dataclass(obj):
        return asdict(obj)
    return str(obj)


def _sse(event_type: str, data: Any) -> str:
    """Format a single SSE event."""
    return f"event: {event_type}\ndata: {json.dumps(data, default=_json_default)}\n\n"
