"""
Command loader — single discovery surface for built-ins + skills.

Source: src/services/customCommands/loadAllCommands.ts.

The dispatcher (``utils.process_user_input.process_slash_command``) calls
``load_all_commands(cwd)`` to populate the lookup table for one turn.
The result merges three streams:

  1. Built-in slash commands (``commands._built_in_commands`` filtered
     through ``filters.meets_availability`` / ``filters.is_command_enabled``).
  2. Bundled skills          (``skills.bundled_skills``).
  3. User + project skills   (``~/.edwin/skills`` and ``<cwd>/.edwin/skills``).

Skills come through ``discover_skills`` which already applies last-wins
layering on collision (project > user > bundled). Built-ins keep their
own namespace — there's no override semantic for collisions between a
built-in and a skill of the same name. A skill named ``help`` would
shadow ``find_command(name)`` lookups by appearing later in the list,
but that's intentional: source treats user-installed commands as
authoritative when they overlap. Don't name your skills after built-ins.

# TODO(2.8.2.x): user/project filesystem-discovered markdown *commands*
# (separate from skills — same parser, different intent). Defer until a
# real consumer needs them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._registry import get_commands
from ..skills.discovery import discover_skills

if TYPE_CHECKING:
    from ..types.command import Command


async def load_all_commands(cwd: str | None = None) -> list["Command"]:
    """Return every command available on this turn — built-ins ∪ skills.

    Order: built-ins first (so the typeahead's empty-prefix view leads
    with them), then skills layered project > user > bundled.
    """
    return [
        *await get_commands(cwd),
        *await discover_skills(cwd),
    ]
