# Phase 6 Lane B — AgentTool port lands across 6.B.1.x:
#   - 6.B.1.1 — types.py: result + output discriminated-union wire schemas.
#               constants.py landed alongside (used by other tools to reference
#               AGENT_TOOL_NAME without forward-decl).
#   - 6.B.1.3 — handler (prompt() + sync call() pre-runAgent), prompt.py,
#               forkSubagent.py stub.
#   - 6.B.1.4 — runAgent dispatch.
#   - 6.B.1.7 — cross-/turn pause/resume via PendingSubagentFrame.
#
# IMPORTANT: this barrel re-exports ONLY the cheap leaves (constants, types,
# exceptions). The AgentTool class itself MUST NOT be imported here — it pulls
# in services.agents, whose built-in agents back-import constants from sibling
# tool packages. Eagerly chaining those imports through ``__init__.py`` creates
# a circular import. Callers grab the live tool from
# ``from app.agent.tools.AgentTool.AgentTool import AgentTool``.

from .constants import (
    AGENT_TOOL_NAME,
    LEGACY_AGENT_TOOL_NAME,
    ONE_SHOT_BUILTIN_AGENT_TYPES,
    VERIFICATION_AGENT_TYPE,
)
from .exceptions import SubagentAwaitingFrontendTools
from .types import (
    AgentToolAsyncOutput,
    AgentToolContentText,
    AgentToolOutput,
    AgentToolResult,
    AgentToolSyncOutput,
    AgentToolUsage,
    AgentToolUsageCacheCreation,
    AgentToolUsageServerToolUse,
    PendingSubagentFrame,
)

__all__ = [
    "AGENT_TOOL_NAME",
    "LEGACY_AGENT_TOOL_NAME",
    "ONE_SHOT_BUILTIN_AGENT_TYPES",
    "VERIFICATION_AGENT_TYPE",
    "AgentToolAsyncOutput",
    "AgentToolContentText",
    "AgentToolOutput",
    "AgentToolResult",
    "AgentToolSyncOutput",
    "AgentToolUsage",
    "AgentToolUsageCacheCreation",
    "AgentToolUsageServerToolUse",
    "PendingSubagentFrame",
    "SubagentAwaitingFrontendTools",
]
