"""ReadMcpResourceTool prompt + name constants."""

READ_MCP_RESOURCE_TOOL_NAME = "ReadMcpResource"

DESCRIPTION = """
Read the contents of a resource exposed by a connected MCP server.

Input:
  - server: the MCP server name
  - uri:    the resource URI (as returned by ListMcpResources)

Output includes `mime`, and either `text` (for text payloads) or
`blob_base64` (for binary payloads). Call ListMcpResources first if you
don't already know the URI.
"""
