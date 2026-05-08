"""
Walk a directory looking for ``*/SKILL.md`` and parse each into a
``PromptCommand``.

Source: src/skills/loadSkillsDir.ts.

Layout:
    <root>/
        outline-deck/
            SKILL.md
        pitch-rewrite/
            SKILL.md            example.html        # sibling files OK; ${SKILL_DIR} resolves here
        ...

Each subdirectory contributes at most one skill. Files at the root of
``<root>`` (i.e. without a containing directory) are ignored — that
matches the source's "one folder per skill" convention and keeps
${SKILL_DIR} useful.

Malformed SKILL.md files (bad YAML, missing required fields,
unreadable) are logged at WARNING and skipped — never throws on a
single bad skill. This is intentional: a typo in one user skill must
not take down the registry for everyone else.
"""

from __future__ import annotations

from pathlib import Path

from app_logger import get_logger

from ..types.command import PromptCommand
from .frontmatter_skill import parse_skill_file

log = get_logger(__name__)


def load_skills_dir(root: Path | str | None, *, source: str = "bundled") -> list[PromptCommand]:
    """Return every successfully-parsed skill in ``<root>/*/SKILL.md``.

    ``source`` ("bundled" / "user" / "project") is forwarded to each
    parsed skill so ``discover_skills`` can implement last-wins layering.

    Returns ``[]`` if ``root`` is None, doesn't exist, or isn't a
    directory — never raises.
    """
    if root is None:
        return []
    root_path = Path(root)
    if not root_path.exists() or not root_path.is_dir():
        return []

    skills: list[PromptCommand] = []
    for child in sorted(root_path.iterdir()):
        if not child.is_dir():
            continue
        skill_md = child / "SKILL.md"
        if not skill_md.is_file():
            continue
        try:
            cmd = parse_skill_file(skill_md, source=source)
        except Exception as e:  # noqa: BLE001
            log.warning(
                "Skipping malformed SKILL.md at %s: %s", skill_md, e,
            )
            continue
        skills.append(cmd)

    return skills
