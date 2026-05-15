"""
MCPTool — fallback dispatcher for invoking MCP server tools by name.

Most usage goes through the per-server tools built by `tool_bridge.build_tools`
(`mcp__<server>__<tool>`). This generic tool covers the case where the model
knows the server + tool name but the wrapper isn't present in the current
tool list (e.g., freshly added server, SDK-style discovery).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app_logger import get_logger

from ...Tool import (
    BaseTool,
    ToolResult,
    ToolUseContext,
    ValidationError,
    ValidationOk,
    ValidationResult,
)
from ...services.mcp.connection_manager import maybe_get_manager
from ...types.hooks import CanUseToolFn
from .prompt import DESCRIPTION, MCP_TOOL_NAME

log = get_logger(__name__)


class MCPInput(BaseModel):
    server: str = Field(description="Configured MCP server name")
    tool: str = Field(description="Remote tool name on that server")
    arguments: dict[str, Any] = Field(
        default_factory=dict,
        description="JSON object of arguments for the remote tool",
    )


class MCPOutput(BaseModel):
    server: str
    tool: str
    content: str
    is_error: bool = False


class MCPToolImpl(BaseTool[MCPInput, MCPOutput]):
    name = MCP_TOOL_NAME
    inputSchema = MCPInput
    maxResultSizeChars = 100_000
    description_text = DESCRIPTION

    # Conservative: we can't know the remote tool's read-only status without
    # resolving the server first. Defaulting to False means plan mode blocks
    # this generic dispatcher — the model should use the per-server tools
    # (each carries its own readOnlyHint) during planning.
    def is_read_only(self, input: Any = None) -> bool:
        return False

    async def description(self, input: Any, options: dict[str, Any]) -> str:
        return DESCRIPTION

    def user_facing_name(self, input: Any = None) -> str:
        return "MCP Call"

    async def prompt(self, options: dict[str, Any]) -> str:
        return DESCRIPTION

    async def validate_input(self, input: Any, context: ToolUseContext) -> ValidationResult:
        parsed = input if isinstance(input, dict) else {}
        if isinstance(input, MCPInput):
            parsed = input.model_dump()
        server = parsed.get("server", "")
        tool = parsed.get("tool", "")
        if not server:
            return ValidationError(message="Missing `server`", errorCode=1)
        if not tool:
            return ValidationError(message="Missing `tool`", errorCode=2)
        return ValidationOk()

    async def call(
        self,
        args: Any,
        context: ToolUseContext,
        can_use_tool: CanUseToolFn,
        parent_message: Any,
        on_progress: Any | None = None,
    ) -> ToolResult[MCPOutput]:
        parsed: MCPInput = (
            args
            if isinstance(args, MCPInput)
            else MCPInput(**(args if isinstance(args, dict) else {}))
        )
        manager = maybe_get_manager()
        if manager is None:
            raise RuntimeError("MCP is not initialized on this server")

        client = await manager.ensure_connected(parsed.server)
        if client is None:
            raise RuntimeError(f"MCP server '{parsed.server}' is unavailable")

        result = await client.call_tool(parsed.tool, parsed.arguments or {})
        output = MCPOutput(
            server=parsed.server,
            tool=parsed.tool,
            content=result.get("content", "") or "",
            is_error=bool(result.get("is_error")),
        )
        if output.is_error:
            raise RuntimeError(output.content or f"{parsed.server}/{parsed.tool} reported an error")
        return ToolResult(data=output, mcpMeta={"server": parsed.server, "tool": parsed.tool})

    def map_tool_result_to_block(self, content: MCPOutput, tool_use_id: str) -> dict[str, Any]:
        text = content.content if isinstance(content, MCPOutput) else str(content)
        return {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": text,
        }


MCPTool = MCPToolImpl()
