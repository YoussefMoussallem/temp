"""`remember` — stub. Will persist a user-supplied note to the backend
memory store in a later phase. Pairs with ``/memory``.

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
            "Remember isn't implemented yet — this command will save a note "
            "to your backend memory store once it ships."
        ),
    }


async def _load():
    return import_module(__name__)


remember: Command = cast(
    Command,
    {
        "type": "local",
        "execution": "server",
        "name": "remember",
        "description": "Save a memory for later (coming soon)",
        "argument_hint": "[text to remember]",
        "aliases": [],
        "supports_non_interactive": True,
        "is_hidden": True,
        "load": _load,
    },
)
