"""`help` — list available slash commands.

Holds both the Command definition and its `call` implementation. The
sibling ``__init__.py`` is a barrel-only re-export per the
``feedback_init_barrel_only`` constraint — no logic in package inits.

Source: src/commands/help.tsx — adapted for the slide webapp (no Ink UI;
returns plain text wrapped in ``LOCAL_COMMAND_STDOUT_TAG`` by the
dispatcher).
"""

from __future__ import annotations

from importlib import import_module
from typing import Any, cast

from ...types.command import Command


async def call(_args: str, _ctx: Any) -> dict:
    # Lazy-imported because ``commands`` package is still loading when this
    # module is first imported (built-ins assembly happens during package
    # init). See registry doc-string for the cycle.
    from ... import commands as commands_mod

    lines = ["Available commands:"]
    for c in commands_mod._built_in_commands():
        if c.get("is_hidden"):
            continue
        name = commands_mod.get_command_name(c)
        desc = c.get("description", "")
        aliases = c.get("aliases") or []
        alias_s = f" (aliases: {', '.join(aliases)})" if aliases else ""
        lines.append(f"  /{name}{alias_s} — {desc}")
    return {"type": "value", "value": "\n".join(lines)}


async def _load():
    # The dispatcher invokes ``cmd.load()`` then ``getattr(mod, 'call')``.
    # Returning this module is the simplest fulfilment of the contract.
    return import_module(__name__)


help: Command = cast(Command, {
    "type": "local",
    "execution": "server",
    "name": "help",
    "description": "Show help and list available commands",
    "aliases": ["?"],
    "supports_non_interactive": True,
    "load": _load,
})
