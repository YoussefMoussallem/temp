"""
Tool registry — assembles all base tools.
"""

from __future__ import annotations

from app_logger import get_logger

from .Tool import Tools
from .services.mcp.connection_manager import maybe_get_manager
from .services.mcp.tool_bridge import build_tools as build_mcp_tools
from .tools.AskUserQuestionTool import AskUserQuestionTool
from .tools.CreateSlideTool import CreateSlideTool
from .tools.DeleteMemoryTool import DeleteMemoryTool
from .tools.DeleteSlideTool import DeleteSlideTool
from .tools.EnterPlanModeTool import EnterPlanModeTool
from .tools.ExitPlanModeTool import ExitPlanModeTool
from .tools.ExportDeckDomTool import ExportDeckDomTool
from .tools.ExportDeckTool import ExportDeckTool
from .tools.ListMcpResourcesTool import ListMcpResourcesTool
from .tools.ListProjectMemoriesTool import ListProjectMemoriesTool
from .tools.ListSlidesTool import ListSlidesTool
from .tools.ListUserMemoriesTool import ListUserMemoriesTool
from .tools.MCPTool import MCPTool
from .tools.ReadMcpResourceTool import ReadMcpResourceTool
from .tools.ReadMemoryTool import ReadMemoryTool
from .tools.ReadSlideTool import ReadSlideTool
from .tools.ReorderSlideTool import ReorderSlideTool
from .tools.SaveProjectMemoryTool import SaveProjectMemoryTool
from .tools.SaveUserMemoryTool import SaveUserMemoryTool
from .tools.SkillTool import SkillTool
from .tools.TodoWriteTool import TodoWriteTool
from .tools.UpdateSlideTool import UpdateSlideTool
from .tools.WebFetchTool import WebFetchTool
from .tools.WebSearchTool import WebSearchTool

log = get_logger(__name__)


def get_all_base_tools() -> Tools:
    """
    Assemble all base tools available to the agent loop.

    Called per request (NOT cached globally) — matches source's pattern,
    so plan-mode gating and live MCP server state (connects/disconnects)
    are reflected without cache invalidation.
    """
    native = [
        AskUserQuestionTool,
        CreateSlideTool,
        DeleteMemoryTool,
        DeleteSlideTool,
        EnterPlanModeTool,
        ExitPlanModeTool,
        ExportDeckTool,
        ExportDeckDomTool,
        ListProjectMemoriesTool,
        ListSlidesTool,
        ListUserMemoriesTool,
        ReadMemoryTool,
        ReadSlideTool,
        ReorderSlideTool,
        SaveProjectMemoryTool,
        SaveUserMemoryTool,
        SkillTool,
        TodoWriteTool,
        UpdateSlideTool,
        WebFetchTool,
        WebSearchTool,
    ]

    mcp_dynamic: list = []
    mcp_native: list = []
    manager = maybe_get_manager()
    if manager is not None:
        try:
            mcp_dynamic = build_mcp_tools(manager)
        except Exception as e:  # noqa: BLE001
            log.warning(f"MCP: build_tools failed, skipping MCP tools this turn: {e}")
        mcp_native = [MCPTool, ListMcpResourcesTool, ReadMcpResourceTool]

    return Tools(tools=native + mcp_dynamic + mcp_native)
