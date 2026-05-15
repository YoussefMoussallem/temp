"""AgentTool constants.

Port of `Utilities/claude files/software agent/src/tools/AgentTool/constants.ts`.
Shipped early (no runtime deps) so other tools can reference AGENT_TOOL_NAME
without forward-decl, and so the upcoming permissions/services scaffolding
can import the canonical names.
"""

AGENT_TOOL_NAME = "Agent"
# Legacy wire name kept for backward compat (permission rules, hooks,
# resumed sessions written before the rename).
LEGACY_AGENT_TOOL_NAME = "Task"
VERIFICATION_AGENT_TYPE = "verification"

# Built-in agents that run once and return a report. Matches source's
# ReadonlySet<string>. Used by the AgentTool finalize trailer to suppress
# the SendMessage routing hint for one-shot agents.
ONE_SHOT_BUILTIN_AGENT_TYPES: frozenset[str] = frozenset({"Explore", "Plan"})
