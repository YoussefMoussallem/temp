"""general-purpose built-in agent.

Matches source ``builtInAgents.ts`` general-purpose: broad multi-tool
agent that can use any tool (``tools=['*']``). Used as the default
``subagent_type`` when AgentTool is invoked without an explicit type.
"""

from __future__ import annotations

from typing import Any

from ..types import BuiltInAgentDefinition


def _get_system_prompt(*, toolUseContext: Any = None) -> str:  # noqa: N803,ARG001
    """System prompt for the general-purpose subagent.

    Mirrors source's general-purpose prompt structure: short identity +
    behavior guidance + reminder to call tools and report concisely. Edwin-
    leaning: this agent runs inside a presentation-authoring host, so the
    behavior block is light on Revit/coding lore and emphasises focused
    execution + structured reporting back to the parent.
    """
    return (
        "You are a general-purpose subagent dispatched by the main "
        "edwin agent to complete a focused task and report back.\n\n"
        "## Role\n"
        "You investigate or execute a delimited task, gather the needed "
        "information using your tools, and return a concise summary the "
        "parent agent can act on. You do not converse with the user "
        "directly — your output is consumed by another agent.\n\n"
        "## Guidance\n"
        "- Stay scoped to the task you were given. Do not expand the brief.\n"
        "- Use the minimum number of tool calls that get the job done.\n"
        "- When you have enough to answer, stop and return a clear, "
        "structured final message — no fluff, no hedging.\n"
        "- Report failures honestly. If a tool errors or returns nothing "
        "useful, say so plainly so the parent can decide how to proceed.\n"
        "- Do not call the Agent tool yourself (no nested subagent dispatch)."
    )


GENERAL_PURPOSE_AGENT: BuiltInAgentDefinition = {
    "agentType": "general-purpose",
    "whenToUse": (
        "General-purpose subagent. Use it for focused investigation or "
        "delimited multi-step tasks that the main agent wants to delegate "
        "and consume the result of."
    ),
    "tools": ["*"],
    "source": "built-in",
    "color": "blue",
    "getSystemPrompt": _get_system_prompt,
}
