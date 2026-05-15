"""Model resolution helper — minimal port of src/utils/model.ts.

Used by ``runAgent`` to pick the subagent's effective model. Resolution
order (source ``getAgentModel``):

  1. Tool-specified model wins (the AgentTool ``model`` arg — deferred
     in v1, always None).
  2. Agent-definition's ``model`` field, unless it's the literal
     ``"inherit"`` (in which case fall through).
  3. Parent's ``mainLoopModel``.

Plan-mode override is dropped in edwin v1 — the source forces Sonnet
under plan mode, but edwin's permission-mode story is simpler (plan
mode just gates write tools, not model selection). When per-mode
overrides ship, restore the gate here.
"""

from __future__ import annotations


def get_agent_model(
    *,
    agent_model: str | None,
    parent_model: str,
    tool_specified_model: str | None,
    permission_mode: str | None = None,
) -> str:
    """Pick the subagent's effective model.

    Empty string is returned only when both ``parent_model`` and
    ``agent_model`` are missing — the LLM call site will surface a clear
    error rather than dispatch with an empty model id.
    """
    if tool_specified_model:
        return tool_specified_model
    if agent_model and agent_model != "inherit":
        return agent_model
    return parent_model or ""
