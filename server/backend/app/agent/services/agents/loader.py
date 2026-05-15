"""Agent definition merge — pure stateless function.

Per the stateless-backend directive, the source TS loader's filesystem
responsibilities (custom + plugin .md reads) live on the frontend. Backend
receives pre-loaded lists in the request payload (empty for edwin v1)
and merges with built-ins here.

Memoization is dropped — backend is stateless. Callers that want per-
request caching can wrap in functools.lru_cache scoped to one request.
"""

from __future__ import annotations

from .built_in_agents import get_builtin_agents
from .types import (
    AgentDefinition,
    AgentDefinitionsResult,
    CustomAgentDefinition,
    is_built_in_agent,
)


def get_active_agents_from_list(
    all_agents: list[AgentDefinition],
) -> list[AgentDefinition]:
    """Dedup by agentType; later-source variants override earlier ones.

    Source precedence (lowest → highest):
        built-in < userSettings < projectSettings < policySettings
    """
    by_type: dict[str, AgentDefinition] = {}
    precedence_order = (
        "built-in",
        "userSettings",
        "projectSettings",
        "policySettings",
    )
    for source in precedence_order:
        for agent in all_agents:
            if agent.get("source") == source:
                by_type[agent["agentType"]] = agent
    return list(by_type.values())


def merge_agent_definitions(
    custom_agents: list[CustomAgentDefinition] | None = None,
) -> AgentDefinitionsResult:
    """Stateless replacement for `getAgentDefinitionsWithOverrides`.

    Args:
        custom_agents: validated custom agents from ``.edwin/agents/*.md``.
            Empty in edwin v1; param exists for parity + future use.

    Returns:
        AgentDefinitionsResult with ``activeAgents`` (post-dedup) and
        ``allAgents`` (pre-dedup union). ``failedFiles`` and
        ``allowedAgentTypes`` are not set here.
    """
    builtins = get_builtin_agents()
    customs = custom_agents or []

    all_agents: list[AgentDefinition] = []
    all_agents.extend(builtins)
    all_agents.extend(customs)

    return AgentDefinitionsResult(
        activeAgents=get_active_agents_from_list(all_agents),
        allAgents=all_agents,
    )


def filter_active_agents_by_allowed_types(
    active_agents: list[AgentDefinition],
    allowed_types: list[str] | None,
) -> list[AgentDefinition]:
    """Per-call AgentTool agentType restriction filter."""
    if not allowed_types:
        return active_agents
    allowed_set = set(allowed_types)
    return [a for a in active_agents if a.get("agentType") in allowed_set]


# ============================================================================
# MCP-requirement filtering
# ============================================================================


def has_required_mcp_servers(
    agent: AgentDefinition,
    available_servers: list[str],
) -> bool:
    """True when the agent has no MCP requirements OR every required
    pattern matches at least one available server (case-insensitive
    substring)."""
    required = agent.get("requiredMcpServers")
    if not required:
        return True
    available_lower = [s.lower() for s in available_servers]
    return all(
        any(pattern.lower() in s for s in available_lower) for pattern in required
    )


def filter_agents_by_mcp_requirements(
    agents: list[AgentDefinition],
    available_servers: list[str],
) -> list[AgentDefinition]:
    return [a for a in agents if has_required_mcp_servers(a, available_servers)]


__all__ = [
    "filter_active_agents_by_allowed_types",
    "filter_agents_by_mcp_requirements",
    "get_active_agents_from_list",
    "has_required_mcp_servers",
    "is_built_in_agent",
    "merge_agent_definitions",
]
