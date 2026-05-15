"""Barrel — re-exports each built-in command + the registry helpers.

The backend owns every command except ``/tasks``, which lives on the
frontend (it reads streamed tool-progress data); the typeahead merges
both sides for unified discovery.

Per ``feedback_init_barrel_only``: only re-exports here, no logic.
"""

from .help import help
from .export import export
from .theme import theme
from .skills import skills
from .new_deck import new_deck
from .plan import plan
from .cost import cost
from .context import context
from .memory import memory
from .remember import remember
from .compact import compact
from .clear import clear

from ._registry import (
    _built_in_commands,
    built_in_command_names,
    get_commands,
    find_command,
    has_command,
    get_command,
    get_command_name,
)
from .filters import is_command_enabled, meets_availability
from .loader import load_all_commands

__all__ = [
    "help",
    "export",
    "theme",
    "skills",
    "new_deck",
    "plan",
    "cost",
    "context",
    "memory",
    "remember",
    "compact",
    "clear",
    "_built_in_commands",
    "built_in_command_names",
    "get_commands",
    "find_command",
    "has_command",
    "get_command",
    "get_command_name",
    "is_command_enabled",
    "meets_availability",
    "load_all_commands",
]
