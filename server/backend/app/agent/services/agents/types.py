"""Agent definition + registry types.

Minimal port of `Utilities/claude files/software agent/src/tools/AgentTool/loadAgentsDir.ts`.
v1 ships the slice AgentTool / runAgent need — built-in + custom variants,
core fields, source-discriminated guards. Plugin agents, hooks, memory
scopes, and effort levels are deferred (BimCode/edwin v1 has no plugin
system or per-agent memory).
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Literal, TypedDict, Union


# UI tag — round-robin pool.
AgentColorName = Literal[
    "red", "blue", "green", "yellow", "purple", "orange", "pink", "cyan",
]
AGENT_COLORS: tuple[AgentColorName, ...] = (
    "red", "blue", "green", "yellow", "purple", "orange", "pink", "cyan",
)


class _BaseAgentDefinitionRequired(TypedDict):
    agentType: str
    whenToUse: str


class BaseAgentDefinition(_BaseAgentDefinitionRequired, total=False):
    """Common fields on every agent variant.

    Tool inventory: ``tools`` defaults to "all" when absent or ``["*"]``;
    ``disallowedTools`` is applied AFTER (deny-list).
    """

    tools: List[str]
    disallowedTools: List[str]
    color: AgentColorName
    model: str
    maxTurns: int
    requiredMcpServers: List[str]
    omitClaudeMd: bool


class _BuiltInAgentRequired(TypedDict):
    source: Literal["built-in"]
    # Receives ``toolUseContext=ctx`` kwarg; returns the system prompt string.
    getSystemPrompt: Callable[..., str]


class BuiltInAgentDefinition(BaseAgentDefinition, _BuiltInAgentRequired, total=False):
    """Built-in agents ship hardcoded as Python modules — no .md round-trip."""


class _CustomAgentRequired(TypedDict):
    getSystemPrompt: Callable[[], str]
    source: Literal["userSettings", "projectSettings", "policySettings"]


class CustomAgentDefinition(BaseAgentDefinition, _CustomAgentRequired, total=False):
    """Loaded from filesystem-side .md files — frontend assembles + sends
    up per stateless-backend directive. Empty in edwin v1."""


AgentDefinition = Union[BuiltInAgentDefinition, CustomAgentDefinition]


def is_built_in_agent(agent: AgentDefinition) -> bool:
    return agent.get("source") == "built-in"


def is_custom_agent(agent: AgentDefinition) -> bool:
    return agent.get("source") not in ("built-in",)


class _AgentDefinitionsResultRequired(TypedDict):
    activeAgents: List[AgentDefinition]
    allAgents: List[AgentDefinition]


class AgentDefinitionsResult(_AgentDefinitionsResultRequired, total=False):
    """Registry shape exposed to ToolUseContext.options.agentDefinitions."""

    failedFiles: List[Dict[str, str]]
    allowedAgentTypes: List[str]
