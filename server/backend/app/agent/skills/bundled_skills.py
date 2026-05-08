"""
Bundled (in-tree) skills shipped with the backend.

Source: src/skills/bundledSkills.ts.

Bundled skills live under ``skills/bundled/<name>/SKILL.md`` and are
loaded via the same filesystem walker as user/project skills — keeping
one parser, one substitution path, one validation. Adding a new bundled
skill is an SKILL.md file, no Python code change.
"""

from __future__ import annotations

from pathlib import Path

from ..types.command import PromptCommand
from .load_skills_dir import load_skills_dir


_BUNDLED_ROOT = Path(__file__).resolve().parent / "bundled"


def bundled_skills() -> list[PromptCommand]:
    """Return every bundled skill. Cheap — re-reads SKILL.md files on
    each call so live-edits during dev surface without a server restart.
    Memoize at the discovery layer if profiling shows this is hot."""
    return load_skills_dir(_BUNDLED_ROOT, source="bundled")
