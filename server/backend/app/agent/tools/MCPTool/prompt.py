"""MCPTool prompt + name constants."""

MCP_TOOL_NAME = "MCP"

DESCRIPTION = """
Dispatch a call to any MCP (Model Context Protocol) server tool by name.

Prefer the namespaced per-server tools (e.g. `mcp__unsplash__search_photos`)
when they are available — this generic tool is a fallback for cases where
you know the server and tool name but the specific wrapper isn't in the
current tool list.

Input:
  - server: the MCP server name from the configured server list
  - tool:   the remote tool's name (as reported by that server)
  - arguments: JSON object of arguments for the remote tool

If the server is unreachable, the call returns an error tool result.
"""
