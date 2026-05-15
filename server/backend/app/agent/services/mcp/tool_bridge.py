"""
MCP tool bridge — turns each remote MCP tool into a local `BaseTool`.

The loop treats MCP tools like any other native tool. The only thing
that's different is:
  - `name` is namespaced `mcp__<server>__<tool>` so the model knows where
    it comes from and can't collide with native names.
  - `input_json_schema()` returns the server's own JSON Schema verbatim
    (not derived from pydantic) — the model sees the real shape.
  - The underlying pydantic `inputSchema` is a permissive passthrough
    (RootModel[dict]) so the loop can `validate_input` without tight
    coupling to the server's exact schema.
  - `call()` forwards to the connection manager; server unavailability
    turns into a readable tool_result, not a loop crash.
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from pydantic import RootModel

from app_logger import get_logger

from ...Tool import BaseTool, ToolResult, ToolUseContext
from ...types.hooks import CanUseToolFn

if TYPE_CHECKING:
    from .connection_manager import McpConnectionManager

log = get_logger(__name__)


class _McpToolInput(RootModel[dict[str, Any]]):
    """Permissive input schema — validation happens server-side."""

    pass


class McpDynamicTool(BaseTool):
    """
    A BaseTool that proxies to one remote MCP tool.

    Each instance is cheap — one wrapper per (server, tool). Instances are
    rebuilt per `/turn` from the connection manager's cached tool list, so
    live server state (disconnects, new tools) is reflected without cache
    invalidation.
    """

    inputSchema = _McpToolInput

    def __init__(
        self,
        server_name: str,
        mcp_tool: dict[str, Any],
        manager: "McpConnectionManager",
    ):
        self._server = server_name
        self._mcp_name = mcp_tool.get("name", "")
        self._description = mcp_tool.get("description", "") or ""
        raw_schema = mcp_tool.get("inputSchema") or {"type": "object", "properties": {}}
        # Some servers return non-dict / bad schemas; coerce to a safe shape.
        self._raw_schema: dict[str, Any] = (
            raw_schema if isinstance(raw_schema, dict) else {"type": "object"}
        )
        self._annotations: dict[str, Any] = mcp_tool.get("annotations") or {}
        self._manager = manager

        self.name = f"mcp__{server_name}__{self._mcp_name}"
        self.isMcp = True
        self.mcpInfo = {"server": server_name, "tool": self._mcp_name}
        # claude.py reads tool descriptions from this attribute when it builds
        # the API tool list; keep it populated so the model sees the full
        # server-authored description.
        self.description_text = self._description

    # ── Capability flags (driven by server annotations) ─────────────────────

    def is_read_only(self, input: Any = None) -> bool:
        # MCP servers signal this via annotations.readOnlyHint. Conservative
        # default: assume writes, so plan-mode gating kicks in.
        return bool(self._annotations.get("readOnlyHint", False))

    def is_concurrency_safe(self, input: Any = None) -> bool:
        return self.is_read_only(input)

    def is_destructive(self, input: Any = None) -> bool:
        return bool(self._annotations.get("destructiveHint", False))

    def is_open_world(self, input: Any = None) -> bool:
        return bool(self._annotations.get("openWorldHint", False))

    # ── Schema / description ────────────────────────────────────────────────

    def input_json_schema(self) -> dict[str, Any]:
        # Bypass pydantic derivation and return the server's own schema.
        return self._raw_schema

    async def description(self, input: Any, options: dict[str, Any]) -> str:
        return self._description

    async def prompt(self, options: dict[str, Any]) -> str:
        return self._description

    def user_facing_name(self, input: Any = None) -> str:
        return f"{self._server}/{self._mcp_name}"

    # ── Execution ───────────────────────────────────────────────────────────

    async def call(
        self,
        args: Any,
        context: ToolUseContext,
        can_use_tool: CanUseToolFn,
        parent_message: Any,
        on_progress: Any | None = None,
    ) -> ToolResult:
        client = await self._manager.ensure_connected(self._server)
        if client is None:
            raise RuntimeError(
                f"MCP server '{self._server}' is unavailable; tool '{self._mcp_name}' cannot run."
            )

        # Accept both dict and RootModel-wrapped args.
        if isinstance(args, _McpToolInput):
            call_args = args.root if isinstance(args.root, dict) else {}
        elif isinstance(args, dict):
            call_args = args
        elif hasattr(args, "model_dump"):
            call_args = args.model_dump()
        else:
            call_args = {}

        try:
            result = await client.call_tool(self._mcp_name, call_args)
        except Exception as e:
            log.exception(f"MCP: '{self._server}.{self._mcp_name}' call failed")
            raise RuntimeError(f"MCP tool '{self.name}' failed: {e}") from e

        if result.get("is_error"):
            # Surface the server's own error through the standard exception
            # path so the loop emits an is_error=True tool_result.
            raise RuntimeError(result.get("content") or "MCP tool reported an error")

        return ToolResult(
            data=result,
            mcpMeta={"server": self._server, "tool": self._mcp_name},
        )

    def map_tool_result_to_block(self, content: Any, tool_use_id: str) -> dict[str, Any]:
        # Prefer the concatenated text; fall back to a compact repr.
        if isinstance(content, dict):
            text = content.get("content")
            if not text and content.get("raw"):
                text = str(content["raw"])
        else:
            text = str(content) if content is not None else ""
        return {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": text or "",
        }


def build_tools(manager: "McpConnectionManager") -> list[BaseTool]:
    """
    Build one `McpDynamicTool` per (connected server, tool). Rebuilt per /turn.
    """
    tools: list[BaseTool] = []
    for status in manager.list_servers():
        if not status.connected:
            continue
        for mcp_tool in status.tools:
            if not mcp_tool.get("name"):
                continue
            tools.append(McpDynamicTool(status.name, mcp_tool, manager))
    return tools
