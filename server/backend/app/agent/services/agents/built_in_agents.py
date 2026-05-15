"""Built-in agent registry — pure entry point.

Returns the edwin-relevant built-in agents. Stateless; no module-level
cache. Caller (router/QueryEngine) decides whether to memoize per request.
"""

from __future__ import annotations

import os

from .built_in import (
    EXPLORE_AGENT,
    GENERAL_PURPOSE_AGENT,
    PLAN_AGENT,
)
from .types import AgentDefinition


def _is_env_truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes"}


def get_builtin_agents() -> list[AgentDefinition]:
    """Honored env var: ``EDWIN_DISABLE_BUILTIN_AGENTS`` → returns []
    when truthy. Used by tests and ops to pin the registry off.
    """
    if _is_env_truthy(os.environ.get("EDWIN_DISABLE_BUILTIN_AGENTS")):
        return []
    return [GENERAL_PURPOSE_AGENT, EXPLORE_AGENT, PLAN_AGENT]
