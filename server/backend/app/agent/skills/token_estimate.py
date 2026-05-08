"""
Cheap token estimation for skill inventory rendering.

Source: src/skills/tokenEstimate.ts (uses cl100k_base via tiktoken).

Edwin doesn't ship a tokenizer dep — and the inventory budget is a soft
cap, not a hard one. We use the standard ~4-chars-per-token approximation,
which is within ~10% of cl100k_base for English prose. Swap to tiktoken
or the model's actual tokenizer when an exact-budget feature shows up.
"""

from __future__ import annotations

from typing import Any


_CHARS_PER_TOKEN = 4
# Per-skill structural overhead — bullets, leading dash, newlines around
# each entry. Calibrated to stay close to tiktoken's accounting.
_SKILL_OVERHEAD_TOKENS = 4


def estimate_chars_tokens(s: str) -> int:
    """char-count / 4, rounded up. Treats whitespace and punctuation
    uniformly — good enough for budgeting prose; not appropriate for
    code or other token-dense content."""
    if not s:
        return 0
    return (len(s) + _CHARS_PER_TOKEN - 1) // _CHARS_PER_TOKEN


def estimate_skill_frontmatter_tokens(skill: dict[str, Any]) -> int:
    """Estimate the token cost of rendering one skill in the inventory.

    Counts the user-facing fields the inventory renderer emits (``name``,
    ``description``, ``when_to_use``, ``argument_hint``, ``aliases``)
    plus a small per-skill structural overhead. Body content is ignored
    — it's not in the inventory, only in the SKILL.md body that fires
    when the skill is invoked.
    """
    chars = (
        len(skill.get("name") or "")
        + len(skill.get("description") or "")
        + len(skill.get("when_to_use") or "")
        + len(skill.get("argument_hint") or "")
        + sum(len(a) for a in (skill.get("aliases") or []))
    )
    return _SKILL_OVERHEAD_TOKENS + (chars + _CHARS_PER_TOKEN - 1) // _CHARS_PER_TOKEN
