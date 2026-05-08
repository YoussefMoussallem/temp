"""Skills package — barrel-only re-exports.

Skills are PromptCommands (Phase 2.7b.1). They flow through the same
dispatcher, registry, XML wrapping, and lifecycle as built-in slash
commands; the only difference is they're authored as ``SKILL.md``
files with YAML frontmatter under ``skills/bundled/<name>/``,
``~/.edwin/skills/<name>/``, or ``<cwd>/.edwin/skills/<name>/``.

Public surface:
  - parse_skill_file:    one SKILL.md → PromptCommand
  - load_skills_dir:     walk a directory → list[PromptCommand]
  - bundled_skills:      in-tree skills shipped with the backend
  - discover_skills:     bundled + user + project, last-wins layered
  - home_skills_dir / project_skills_dir: standard locations
"""

from .frontmatter_skill import parse_skill_file
from .load_skills_dir import load_skills_dir
from .bundled_skills import bundled_skills
from .discovery import discover_skills, home_skills_dir, project_skills_dir
from .inventory import render_skills_inventory
from .token_estimate import (
    estimate_chars_tokens,
    estimate_skill_frontmatter_tokens,
)

__all__ = [
    "parse_skill_file",
    "load_skills_dir",
    "bundled_skills",
    "discover_skills",
    "home_skills_dir",
    "project_skills_dir",
    "render_skills_inventory",
    "estimate_chars_tokens",
    "estimate_skill_frontmatter_tokens",
]
