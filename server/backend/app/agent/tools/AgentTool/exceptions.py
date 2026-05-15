"""AgentTool-specific exceptions.

Port of RevitCode `tools/AgentTool/exceptions.py`. Phase 6.B.1.7.
Edwin-specific (TS source has no equivalent — its subagent loop runs
entirely in-process).

When AgentTool's inner query() yields Terminal(reason="awaiting_frontend_tools")
because the subagent emitted frontend-executed tool_uses, the subagent loop
CANNOT complete in this /turn: the tool results round-trip via chat-ui
across the next /turn boundary. AgentTool.call() raises
`SubagentAwaitingFrontendTools` to signal the pause to
query_loop._execute_single_tool, which converts it into the per-tool-runner's
pause payload.

The frame field is a `PendingSubagentFrame` dict (see
`tools/AgentTool/types.py`); the `tool_uses` field is a list of the
subagent's pending tool_use blocks (the inner query()'s tool_request
payload, parallel + sequential combined).
"""

from __future__ import annotations

from typing import Any


class SubagentAwaitingFrontendTools(Exception):
    """Subagent's inner query() reached awaiting_frontend_tools.

    Carries the subagent state to persist + the tool_uses to lift into
    the parent's frontend dispatch. ``parentToolUseId`` is set by
    query_loop._execute_single_tool's catch site (the frame's author —
    AgentTool.call() — doesn't have ready access to its own tool_use_id).
    """

    def __init__(
        self,
        *,
        frame: dict[str, Any],
        tool_uses: list[dict[str, Any]],
    ) -> None:
        self.frame = frame
        self.tool_uses = tool_uses
        super().__init__(
            f"subagent {frame.get('agentId', '?')} awaiting frontend tools "
            f"({len(tool_uses)} pending)"
        )
