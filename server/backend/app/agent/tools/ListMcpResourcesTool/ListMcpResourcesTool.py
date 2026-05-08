"""
ListMcpResourcesTool — enumerate resources across connected MCP servers.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from app_logger import get_logger

from ...Tool import BaseTool, ToolResult, ToolUseContext
from ...services.mcp.connection_manager import maybe_get_manager
from ...services.mcp.resource_bridge import list_resources
from ...types.hooks import CanUseToolFn
from .prompt import DESCRIPTION, LIST_MCP_RESOURCES_TOOL_NAME

log = get_logger(__name__)


class ListMcpResourcesInput(BaseModel):
    server: str | None = Field(
        default=None,
        description="Optional: restrict to a single MCP server name",
    )


class ListMcpResourcesOutput(BaseModel):
    resources: list[dict[str, Any]]


class ListMcpResourcesToolImpl(BaseTool[ListMcpResourcesInput, ListMcpResourcesOutput]):
    name = LIST_MCP_RESOURCES_TOOL_NAME
    inputSchema = ListMcpResourcesInput
    maxResultSizeChars = 100_000
    description_text = DESCRIPTION

    def is_read_only(self, input: Any = None) -> bool:
        return True

    def is_concurrency_safe(self, input: Any = None) -> bool:
        return True

    async def description(self, input: Any, options: dict[str, Any]) -> str:
        return DESCRIPTION

    def user_facing_name(self, input: Any = None) -> str:
        return "List MCP Resources"

    async def prompt(self, options: dict[str, Any]) -> str:
        return DESCRIPTION

    async def call(
        self,
        args: Any,
        context: ToolUseContext,
        can_use_tool: CanUseToolFn,
        parent_message: Any,
        on_progress: Any | None = None,
    ) -> ToolResult[ListMcpResourcesOutput]:
        parsed: ListMcpResourcesInput = (
            args
            if isinstance(args, ListMcpResourcesInput)
            else ListMcpResourcesInput(**(args if isinstance(args, dict) else {}))
        )
        manager = maybe_get_manager()
        if manager is None:
            raise RuntimeError("MCP is not initialized on this server")

        entries = await list_resources(manager, parsed.server)
        return ToolResult(data=ListMcpResourcesOutput(resources=entries))

    def map_tool_result_to_block(
        self, content: ListMcpResourcesOutput, tool_use_id: str
    ) -> dict[str, Any]:
        if isinstance(content, ListMcpResourcesOutput):
            payload = json.dumps(content.resources, default=str)
        else:
            payload = str(content)
        return {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": payload,
        }


ListMcpResourcesTool = ListMcpResourcesToolImpl()
