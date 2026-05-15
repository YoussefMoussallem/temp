"""
Resource helpers shared by ListMcpResourcesTool / ReadMcpResourceTool.

Thin wrappers around the connection manager so the tools stay small.
"""

from __future__ import annotations

import asyncio
from typing import Any, TYPE_CHECKING

from app_logger import get_logger

if TYPE_CHECKING:
    from .connection_manager import McpConnectionManager

log = get_logger(__name__)


async def list_resources(
    manager: "McpConnectionManager",
    server_filter: str | None = None,
) -> list[dict[str, Any]]:
    """
    Fan out to connected servers (or just one, if `server_filter` is set)
    and return a flat list tagged with the owning server name.
    """
    statuses = [s for s in manager.list_servers() if s.connected]
    if server_filter:
        statuses = [s for s in statuses if s.name == server_filter]

    async def _one(name: str) -> list[dict[str, Any]]:
        client = await manager.ensure_connected(name)
        if client is None:
            return []
        try:
            entries = await client.list_resources()
        except Exception as e:  # noqa: BLE001
            log.warning(f"MCP: list_resources('{name}') failed: {e}")
            return []
        return [{"server": name, **entry} for entry in entries]

    results = await asyncio.gather(*[_one(s.name) for s in statuses], return_exceptions=False)
    out: list[dict[str, Any]] = []
    for chunk in results:
        out.extend(chunk)
    return out


async def read_resource(
    manager: "McpConnectionManager",
    server: str,
    uri: str,
) -> dict[str, Any]:
    client = await manager.ensure_connected(server)
    if client is None:
        raise RuntimeError(f"MCP server '{server}' is unavailable")
    return await client.read_resource(uri)
