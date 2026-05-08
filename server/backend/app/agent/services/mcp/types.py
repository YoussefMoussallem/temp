"""
MCP service types — internal dataclasses shared across the service layer.

Kept Pydantic-free: nothing leaves this package boundary as a type, so plain
dataclasses are simpler and cheaper. Tool input schemas that DO cross the
Tool abstraction use Pydantic (see tool_bridge.McpDynamicTool).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Union


@dataclass
class StdioServerConfig:
    """MCP server launched as a subprocess, speaking MCP over stdin/stdout."""
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class HttpServerConfig:
    """Remote MCP server over streamable HTTP."""
    name: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)


ServerConfig = Union[StdioServerConfig, HttpServerConfig]


@dataclass
class ServerStatus:
    """
    Snapshot of a server's live state, produced by the connection manager.

    `tools` holds the raw MCP tool descriptors (dicts with keys name, description,
    inputSchema, annotations) as returned by the server's tools/list call.
    """
    name: str
    connected: bool
    error: str | None = None
    tools: list[dict[str, Any]] = field(default_factory=list)


class MissingEnvVarError(RuntimeError):
    """Raised at config-load time when a ${VAR} reference has no matching env var."""
