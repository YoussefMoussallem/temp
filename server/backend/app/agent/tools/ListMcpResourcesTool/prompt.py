"""ListMcpResourcesTool prompt + name constants."""

LIST_MCP_RESOURCES_TOOL_NAME = "ListMcpResources"

DESCRIPTION = """
List resources exposed by connected MCP servers.

Each entry includes `server`, `uri`, `name`, `description`, and `mimeType`.
Use this to discover what a server exposes before calling ReadMcpResource.

Input:
  - server: optional; restrict to a single server name. Omit to list across
    all connected servers.
"""
