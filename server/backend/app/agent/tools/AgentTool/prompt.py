"""AgentTool description prompt.

Renders the per-agent listing the LLM sees inside AgentTool's tool
description. Source: ``tools/AgentTool/prompt.ts``. Edwin-leaning: simpler
preamble + identical agent listing format so the model can pick a
``subagent_type`` deterministically.
"""

from __future__ import annotations

from typing import Any


_PREAMBLE = (
    "Launch a new subagent to handle complex, multi-step tasks autonomously.\n"
    "Each agent type has specific capabilities and tools available.\n\n"
    "## Available agent types\n"
)

_USAGE_NOTES = """

## Usage notes

- Each invocation is stateless. The agent runs to completion and returns
  a single final message; you cannot have a back-and-forth conversation
  with a running agent.
- Always include a short description summarising what the agent will do.
- The agent's final message is the only thing you'll see — provide enough
  context in the prompt for the agent to complete the task on its own.
- When you launch multiple agents for independent work, send them in a
  single message with multiple tool uses so they run concurrently.
- The user will not see the agent's intermediate work — you must
  communicate the final result back to the user yourself."""


async def get_prompt(
    agents: list[dict[str, Any]],
    is_coordinator: Any = None,  # noqa: ARG001 — coordinator gate deferred
    allowed_agent_types: list[str] | None = None,
) -> str:
    """Build the AgentTool prompt body listing the agents the model can pick.

    ``agents`` is the post-MCP-filter list from AgentTool.prompt(). When
    ``allowed_agent_types`` is set (per-spec restriction), filter the
    listing to that subset.
    """
    visible = agents
    if allowed_agent_types:
        allowed_set = set(allowed_agent_types)
        visible = [a for a in agents if a.get("agentType") in allowed_set]

    if not visible:
        return (
            _PREAMBLE
            + "(no agents available — check MCP server requirements)\n"
            + _USAGE_NOTES
        )

    lines = [_PREAMBLE]
    for agent in visible:
        agent_type = agent.get("agentType", "")
        when = agent.get("whenToUse", "")
        tools = agent.get("tools") or ["*"]
        tools_str = "all" if tools == ["*"] else ", ".join(tools)
        lines.append(f"- **{agent_type}**: {when}")
        lines.append(f"  - Tools: {tools_str}")
    return "\n".join(lines) + _USAGE_NOTES
