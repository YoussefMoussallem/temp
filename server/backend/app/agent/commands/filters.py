"""
Command availability + enablement filters.

Source: src/commands.ts (the inline ``meetsAvailability`` /
``isCommandEnabled`` helpers). Extracted into a sibling module so the
registry stays focused on lookup, and so user/project command discovery
(Phase 2.8.2.x) can re-use the same filters without importing the
registry's private surface.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..types.command import Command


def meets_availability(c: "Command") -> bool:
    """A command without ``availability`` declared is universally available.

    When declared, it must include ``"interactive"`` to surface in the slide
    webapp — v1 only ever runs interactive turns.
    """
    avail = c.get("availability")
    if not avail:
        return True
    return "interactive" in avail


def is_command_enabled(c: "Command") -> bool:
    """Resolve the ``is_enabled`` callable, defaulting to True. A raising
    callable is treated as disabled — never let a buggy predicate take
    down the registry."""
    fn = c.get("is_enabled")
    if callable(fn):
        try:
            return bool(fn())
        except Exception:  # noqa: BLE001
            return False
    return True
