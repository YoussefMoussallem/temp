"""
ReadMcpResourceTool — fetch a resource's contents from an MCP server.
"""

from __future__ import annotations

import json
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
from ...services.mcp.resource_bridge import read_resource
from ...types.hooks import CanUseToolFn
from .prompt import DESCRIPTION, READ_MCP_RESOURCE_TOOL_NAME

log = get_logger(__name__)


class ReadMcpResourceInput(BaseModel):
    server: str = Field(description="The MCP server name")
    uri: str = Field(description="Resource URI to read")


class ReadMcpResourceOutput(BaseModel):
    server: str
    uri: str
    mime: str | None = None
    text: str | None = None
    blob_base64: str | None = None


class ReadMcpResourceToolImpl(BaseTool[ReadMcpResourceInput, ReadMcpResourceOutput]):
    name = READ_MCP_RESOURCE_TOOL_NAME
    inputSchema = ReadMcpResourceInput
    maxResultSizeChars = 500_000  # resources can be sizeable documents
    description_text = DESCRIPTION

    def is_read_only(self, input: Any = None) -> bool:
        return True

    def is_concurrency_safe(self, input: Any = None) -> bool:
        return True

    async def description(self, input: Any, options: dict[str, Any]) -> str:
        return DESCRIPTION

    def user_facing_name(self, input: Any = None) -> str:
        return "Read MCP Resource"

    async def prompt(self, options: dict[str, Any]) -> str:
        return DESCRIPTION

    async def validate_input(self, input: Any, context: ToolUseContext) -> ValidationResult:
        parsed = input if isinstance(input, dict) else {}
        if isinstance(input, ReadMcpResourceInput):
            parsed = input.model_dump()
        if not parsed.get("server"):
            return ValidationError(message="Missing `server`", errorCode=1)
        if not parsed.get("uri"):
            return ValidationError(message="Missing `uri`", errorCode=2)
        return ValidationOk()

    async def call(
        self,
        args: Any,
        context: ToolUseContext,
        can_use_tool: CanUseToolFn,
        parent_message: Any,
        on_progress: Any | None = None,
    ) -> ToolResult[ReadMcpResourceOutput]:
        parsed: ReadMcpResourceInput = (
            args
            if isinstance(args, ReadMcpResourceInput)
            else ReadMcpResourceInput(**(args if isinstance(args, dict) else {}))
        )
        manager = maybe_get_manager()
        if manager is None:
            raise RuntimeError("MCP is not initialized on this server")

        result = await read_resource(manager, parsed.server, parsed.uri)
        return ToolResult(
            data=ReadMcpResourceOutput(
                server=parsed.server,
                uri=parsed.uri,
                mime=result.get("mime"),
                text=result.get("text"),
                blob_base64=result.get("blob_base64"),
            ),
            mcpMeta={"server": parsed.server, "uri": parsed.uri},
        )

    def map_tool_result_to_block(
        self, content: ReadMcpResourceOutput, tool_use_id: str
    ) -> dict[str, Any]:
        if isinstance(content, ReadMcpResourceOutput):
            payload = json.dumps(content.model_dump(), default=str)
        else:
            payload = str(content)
        return {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": payload,
        }


ReadMcpResourceTool = ReadMcpResourceToolImpl()
