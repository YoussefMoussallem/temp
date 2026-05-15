"""Agent definition + registry services — barrel."""

from .built_in import EXPLORE_AGENT, GENERAL_PURPOSE_AGENT, PLAN_AGENT
from .built_in_agents import get_builtin_agents
from .loader import (
    filter_active_agents_by_allowed_types,
    filter_agents_by_mcp_requirements,
    get_active_agents_from_list,
    has_required_mcp_servers,
    merge_agent_definitions,
)
from .types import (
    AGENT_COLORS,
    AgentColorName,
    AgentDefinition,
    AgentDefinitionsResult,
    BaseAgentDefinition,
    BuiltInAgentDefinition,
    CustomAgentDefinition,
    is_built_in_agent,
    is_custom_agent,
)

__all__ = [
    "AGENT_COLORS",
    "AgentColorName",
    "AgentDefinition",
    "AgentDefinitionsResult",
    "BaseAgentDefinition",
    "BuiltInAgentDefinition",
    "CustomAgentDefinition",
    "EXPLORE_AGENT",
    "GENERAL_PURPOSE_AGENT",
    "PLAN_AGENT",
    "filter_active_agents_by_allowed_types",
    "filter_agents_by_mcp_requirements",
    "get_active_agents_from_list",
    "get_builtin_agents",
    "has_required_mcp_servers",
    "is_built_in_agent",
    "is_custom_agent",
    "merge_agent_definitions",
]
