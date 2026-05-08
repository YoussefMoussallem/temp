"""
Command registry — built-in list + lookup helpers.

Port of src/commands.ts. Source lives there as a flat .ts file because JS
doesn't have the package-vs-module ambiguity Python has. Here, the package
``agent.commands/`` already exists for built-in implementations, so the
registry lives at ``agent.commands._registry`` and is re-exported through
``agent.commands.__init__``. Callers should import via:
    from app.agent.commands import find_command, has_command, get_commands

Filter predicates (``meets_availability`` / ``is_command_enabled``) live
in ``commands.filters`` so user/project command discovery can share them.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from .filters import is_command_enabled, meets_availability

if TYPE_CHECKING:
    from ..types.command import Command


@lru_cache(maxsize=1)
def _built_in_commands() -> list["Command"]:
    """Memoized static list of server-executing commands.

    The backend owns every command except ``/tasks``, which still lives on
    the frontend (it reads streamed tool-progress data) and is merged into
    the typeahead there.

    Hidden commands (``is_hidden=True``) stay registered so they still
    resolve when typed, but don't surface in ``/help`` or the typeahead.
    Currently hidden: ``/memory``, ``/remember`` (stubs awaiting full
    implementations). ``/compact`` was un-hidden in Phase 3.2.

    Deferred: user/project command filesystem loading
    (Phase 2.8.2.x — see ``loader.load_all_commands``).
    """
    from . import (
        help, export, theme, skills, new_deck,
        plan, cost, context, memory, remember, compact, clear,
    )
    return [
        help, export, theme, skills, new_deck,
        plan, cost, context, memory, remember, compact, clear,
    ]


@lru_cache(maxsize=1)
def built_in_command_names() -> frozenset[str]:
    """All primary names + aliases. Source: src/commands.ts:348."""
    names: set[str] = set()
    for c in _built_in_commands():
        name = c.get("name")
        if name:
            names.add(name)
        names.update(c.get("aliases", []) or [])
    return frozenset(names)


async def get_commands(cwd: str | None = None) -> list["Command"]:
    """Source: src/commands.ts:476 ``getCommands``. v1 skips dynamic-skills
    insertion (Phase 2.7b). ``cwd`` is accepted for signature parity and
    for the future user/project filesystem discovery in
    ``loader.load_all_commands``."""
    all_commands = _built_in_commands()
    return [c for c in all_commands if meets_availability(c) and is_command_enabled(c)]


def get_command_name(c: "Command") -> str:
    """User-facing name. Falls back to ``name``. Source: src/commands.ts."""
    ufn = c.get("user_facing_name")
    if callable(ufn):
        try:
            v = ufn()
            if isinstance(v, str) and v:
                return v
        except Exception:  # noqa: BLE001
            pass
    return c.get("name", "")


def find_command(name: str, commands: list["Command"]) -> "Command | None":
    """O(n) scan over primary name + user-facing name + aliases. Case-insensitive."""
    if not name:
        return None
    needle = name.lower()
    for c in commands:
        if (c.get("name") or "").lower() == needle:
            return c
        if get_command_name(c).lower() == needle:
            return c
        if needle in {a.lower() for a in (c.get("aliases") or [])}:
            return c
    return None


def has_command(name: str, commands: list["Command"]) -> bool:
    return find_command(name, commands) is not None


def get_command(name: str, commands: list["Command"]) -> "Command":
    """Raises ReferenceError with an informative message. Matches source."""
    cmd = find_command(name, commands)
    if cmd is None:
        names = sorted(get_command_name(c) for c in commands)
        raise ReferenceError(
            f"Command {name!r} not found. Available: {', '.join(names)}"
        )
    return cmd
