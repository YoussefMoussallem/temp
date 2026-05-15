"""`skills` — list bundled skills. Server-executing because the backend
owns the skill registry.

Holds both the Command definition and its ``call`` implementation. The
sibling ``__init__.py`` is a barrel-only re-export per the
``feedback_init_barrel_only`` constraint.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any, cast

from ...types.command import Command


async def call(_args: str, _ctx: Any) -> dict:
    """List discovered skills (bundled + ~/.edwin/skills + project layer).

    Skills are PromptCommands since Phase 2.7b.1 — same shape as
    built-ins. We filter by ``loaded_from == "skills"`` to keep this
    listing distinct from the broader ``/help`` output.
    """
    try:
        from ...skills.discovery import discover_skills
    except Exception as e:  # noqa: BLE001
        return {"type": "value", "value": f"Skills unavailable: {e}"}

    discovered = await discover_skills()
    visible = [s for s in discovered if not s.get("is_hidden")]
    if not visible:
        return {"type": "value", "value": "No skills registered."}
    lines = ["Available skills:"]
    for s in visible:
        name = s.get("name", "?")
        desc = s.get("description", "") or ""
        aliases = list(s.get("aliases") or [])
        alias_s = f" ({', '.join(aliases)})" if aliases else ""
        lines.append(f"  /{name}{alias_s} — {desc}")
    return {"type": "value", "value": "\n".join(lines)}


async def _load():
    return import_module(__name__)


skills: Command = cast(
    Command,
    {
        "type": "local",
        "execution": "server",
        "name": "skills",
        "description": "List available skills",
        "aliases": [],
        "supports_non_interactive": True,
        "load": _load,
    },
)
