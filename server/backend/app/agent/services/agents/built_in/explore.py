"""Explore built-in agent — read-only investigation specialist.

Mirrors source's Explore agent. Tool allowlist is read-only so the parent
can dispatch wide research without risking mutation. Listed in
``ONE_SHOT_BUILTIN_AGENT_TYPES`` so the AgentTool finalize trailer
suppresses the SendMessage hint (Explore returns once and is done).
"""

from __future__ import annotations

from typing import Any

from ..types import BuiltInAgentDefinition


def _get_system_prompt(*, toolUseContext: Any = None) -> str:  # noqa: N803,ARG001
    return (
        "You are the Explore subagent — a read-only investigator dispatched "
        "by the main edwin agent to find information without mutating state.\n\n"
        "## Role\n"
        "Search the slide deck and surrounding context using your read-only "
        "tools. Locate the requested information, summarise what you found, "
        "and return a concise structured report to the parent agent.\n\n"
        "## Guidance\n"
        "- Read-only only: you have no write or mutating tools. Don't ask for them.\n"
        "- Be exhaustive within the scope of the request — read what you need, "
        "  but no more.\n"
        "- Return one final answer. Don't loop; don't ask the user questions.\n"
        "- If you can't find the answer, say so plainly with whatever partial "
        "  evidence you gathered."
    )


EXPLORE_AGENT: BuiltInAgentDefinition = {
    "agentType": "Explore",
    "whenToUse": (
        "Read-only investigation. Use for locating slides, content, or "
        "context across a deck without mutating anything. Returns once "
        "with a final report."
    ),
    # Read-only allowlist — no slide-writing, no memory-writing, no skill
    # invocation. Parent dispatches Explore exactly when it wants safety.
    "tools": [
        "ReadSlide",
        "ListSlides",
        "ListProjectMemories",
        "ListUserMemories",
        "ReadMemory",
        "WebSearch",
        "WebFetch",
    ],
    "source": "built-in",
    "color": "cyan",
    "getSystemPrompt": _get_system_prompt,
}
