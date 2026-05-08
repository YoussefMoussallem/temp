"""
Render the available-skills inventory for the system prompt.

Source: src/skills/inventory.ts.

The inventory is a markdown section appended to the system prompt that
tells the LLM which skills exist and when to invoke each one. Without
it, even with a SkillTool registered, the model has no way to know
``/outline-deck`` exists — the SkillTool's tool description doesn't
list every skill (would explode token cost on every call).

Token budget: ~2000 tokens by default, soft cap. If skills exceed the
budget we drop tail skills (assuming they're sorted by predicted
relevance — currently insertion order from ``discover_skills``, which
is project > user > bundled). A future version can rank by recency
or LLM-predicted relevance per turn.
"""

from __future__ import annotations

from typing import Any, Iterable

from .token_estimate import estimate_chars_tokens, estimate_skill_frontmatter_tokens


_HEADER = "\n\n---\n\n## Available skills\n"
_PREAMBLE = (
    "These named skills are reusable prompt templates registered with "
    "the agent. Invoke a skill when one matches the user's intent by "
    "calling the `Skill` tool with `{name, args}` — e.g. "
    "`Skill({name: \"outline-deck\", args: \"AI agents for architects\"})`. "
    "The tool returns the skill's instruction template; follow those "
    "instructions in your next response. Prefer invoking a relevant "
    "skill over re-deriving its behavior from scratch. Do not re-invoke "
    "a skill the user already triggered with a slash command (`/skill`) "
    "— the dispatcher already handled that.\n"
)


def _as_str(v: Any) -> str:
    """Defensive: a malformed PromptCommand built outside the loader
    might pass a list/None where a string is expected. The system prompt
    must never crash a turn — fall back to str() and let the model
    interpret the output."""
    if v is None:
        return ""
    return v if isinstance(v, str) else str(v)


def _render_skill(skill: dict[str, Any]) -> str:
    """One skill as a bullet block. Stable, predictable shape so the LLM
    can pattern-match the format across the inventory."""
    name = _as_str(skill.get("name"))
    description = _as_str(skill.get("description")).strip()
    when_to_use = _as_str(skill.get("when_to_use")).strip()
    arg_hint = _as_str(skill.get("argument_hint")).strip()
    aliases = list(skill.get("aliases") or [])

    lines = [f"- `/{name}` — {description}"]
    if when_to_use:
        lines.append(f"  - When to use: {when_to_use}")
    if arg_hint:
        lines.append(f"  - Args: {arg_hint}")
    if aliases:
        lines.append(f"  - Aliases: {', '.join(aliases)}")
    return "\n".join(lines)


def render_skills_inventory(
    skills: Iterable[dict[str, Any]],
    *,
    max_tokens: int = 2000,
) -> str:
    """Return the markdown inventory block, or '' if no visible skills.

    Skills with ``is_hidden: True`` are omitted entirely — they exist for
    internal use (e.g. a SkillTool sub-call) and shouldn't tempt the
    model. ``disable_model_invocation: True`` also hides — those are
    user-only skills.

    Truncation: when adding the next skill would exceed ``max_tokens``,
    we stop and append a "(N more skills available, run /skills to see all)"
    footer so the model knows the list is incomplete.
    """
    visible = [
        s for s in skills
        if not s.get("is_hidden")
        and not s.get("disable_model_invocation")
    ]
    if not visible:
        return ""

    header_tokens = estimate_chars_tokens(_HEADER + _PREAMBLE)
    # Reserve some budget for the footer (worst case: we truncate).
    footer_reserve = 30
    budget = max_tokens - header_tokens - footer_reserve

    rendered: list[str] = []
    used = 0
    dropped = 0

    for s in visible:
        cost = estimate_skill_frontmatter_tokens(s)
        if used + cost > budget and rendered:
            # We've already rendered at least one skill; stop and tally
            # what's left as dropped.
            dropped = len(visible) - len(rendered)
            break
        rendered.append(_render_skill(s))
        used += cost

    if not rendered:
        return ""

    parts = [_HEADER, _PREAMBLE, "\n".join(rendered)]
    if dropped > 0:
        parts.append(
            f"\n\n_({dropped} more skill"
            f"{'s' if dropped != 1 else ''} available — "
            f"run `/skills` for the full list.)_"
        )
    return "\n".join(parts)
