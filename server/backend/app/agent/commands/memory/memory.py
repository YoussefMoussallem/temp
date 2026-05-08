"""`memory` — stub. Will list/manage saved user memories from the backend
in a later phase. Registered now so it surfaces in ``/help`` and the
typeahead while the implementation is under design.

Holds both the Command definition and its ``call`` implementation. The
sibling ``__init__.py`` is a barrel-only re-export per the
``feedback_init_barrel_only`` constraint.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any, cast

from ...types.command import Command


async def call(_args: str, _ctx: Any) -> dict:
    return {
        "type": "value",
        "value": (
            "Memory isn't implemented yet — this command will list and "
            "manage your saved memories once the backend memory store ships."
        ),
    }


async def _load():
    return import_module(__name__)


memory: Command = cast(Command, {
    "type": "local",
    "execution": "server",
    "name": "memory",
    "description": "Manage saved memories (coming soon)",
    "aliases": [],
    "supports_non_interactive": True,
    "is_hidden": True,
    "load": _load,
})
