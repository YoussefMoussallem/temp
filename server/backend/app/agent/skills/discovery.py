"""
Skill discovery — single entry point used by the command registry.

Source: src/skills/discoverSkills.ts.

Three layers, last-wins on name collision:
  1. Bundled (in-tree under skills/bundled/)
  2. User    (~/.edwin/skills/)
  3. Project (<cwd>/.edwin/skills/)

A project skill named ``outline-deck`` shadows a user-level one, which
shadows a bundled one. Aliases are not de-duplicated — only the
primary ``name`` field decides identity (matching source semantics).

Result is a flat ``list[PromptCommand]`` ready to be unioned with the
built-in commands in ``commands.loader.load_all_commands``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

from ..types.command import PromptCommand
from .bundled_skills import bundled_skills
from .load_skills_dir import load_skills_dir


def home_skills_dir() -> Path:
    """``~/.edwin/skills`` — same convention as
    ``commands.loader.load_all_commands``'s future user-command discovery."""
    return Path(os.path.expanduser("~")) / ".edwin" / "skills"


def project_skills_dir(cwd: str | Path | None) -> Path | None:
    """``<cwd>/.edwin/skills`` — None if no cwd given, so callers don't
    have to defend against missing env."""
    if not cwd:
        return None
    return Path(cwd) / ".edwin" / "skills"


def _dedupe_last_wins(layers: Iterable[list[PromptCommand]]) -> list[PromptCommand]:
    """Merge layers with last-wins on the ``name`` field. Preserves the
    insertion order of the first occurrence so the typeahead doesn't
    reshuffle when a user adds a project-level override."""
    by_name: dict[str, PromptCommand] = {}
    order: list[str] = []
    for layer in layers:
        for cmd in layer:
            name = cmd.get("name") or ""
            if not name:
                continue
            if name not in by_name:
                order.append(name)
            by_name[name] = cmd
    return [by_name[n] for n in order]


async def discover_skills(cwd: str | Path | None = None) -> list[PromptCommand]:
    """Return every skill available to this turn, with project > home >
    bundled layering applied.

    Async because future implementations may stat files concurrently or
    fetch from a remote skill registry — keeping the signature async-ready
    means callers don't churn when that lands.
    """
    return _dedupe_last_wins(
        [
            bundled_skills(),
            load_skills_dir(home_skills_dir(), source="user"),
            load_skills_dir(project_skills_dir(cwd), source="project"),
        ]
    )
