"""Plan built-in agent — outline-first scaffolder.

Mirrors source's Plan agent. Read-only investigation tools plus
``TodoWrite`` and ``ExitPlanMode`` so it can structure a plan and submit
it for approval. Listed in ``ONE_SHOT_BUILTIN_AGENT_TYPES`` so the
AgentTool trailer suppresses the SendMessage hint.
"""

from __future__ import annotations

from typing import Any

from ..types import BuiltInAgentDefinition


def _get_system_prompt(*, toolUseContext: Any = None) -> str:  # noqa: N803,ARG001
    return (
        "You are the Plan subagent — a planning specialist dispatched by "
        "the main edwin agent to draft an approach without executing it.\n\n"
        "## Role\n"
        "Read context, structure the work into clear steps via TodoWrite, "
        "and submit the plan for approval via ExitPlanMode. You do not "
        "make changes to the deck — your output is the plan itself.\n\n"
        "## Guidance\n"
        "- Use TodoWrite to lay out every step before submitting.\n"
        "- Keep steps concrete and ordered; avoid hand-wavy phrasing.\n"
        "- Call ExitPlanMode with the full markdown plan when it's ready.\n"
        "- Do NOT call CreateSlide / UpdateSlide / DeleteSlide / "
        "ReorderSlide — those are for the executing agent."
    )


PLAN_AGENT: BuiltInAgentDefinition = {
    "agentType": "Plan",
    "whenToUse": (
        "Drafting a plan before executing changes. Use when the user "
        "wants the approach reviewed before slides are touched."
    ),
    "tools": [
        "ReadSlide",
        "ListSlides",
        "ListProjectMemories",
        "ListUserMemories",
        "ReadMemory",
        "WebSearch",
        "WebFetch",
        "TodoWrite",
        "ExitPlanMode",
    ],
    "source": "built-in",
    "color": "yellow",
    "getSystemPrompt": _get_system_prompt,
}
