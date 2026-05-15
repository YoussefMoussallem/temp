"""
MCP server config loader.

Reads a YAML file describing which MCP servers to connect to at startup.
Env-var references (`${VAR}`) are expanded eagerly; a missing var fails
loudly so operators notice before the server starts serving traffic.

Path resolution:
  1. $MCP_CONFIG_PATH
  2. <backend_root>/mcp_servers.yaml       (gitignored; the real config)
  3. <backend_root>/mcp_servers.example.yaml  (committed; usually empty)
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

from app_logger import get_logger

from .types import (
    HttpServerConfig,
    MissingEnvVarError,
    ServerConfig,
    StdioServerConfig,
)

log = get_logger(__name__)

_BACKEND_ROOT = Path(__file__).resolve().parents[4]
_ENV_VAR_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")


def _resolve_config_path(explicit: Path | None) -> Path | None:
    if explicit is not None:
        return explicit if explicit.exists() else None
    env_path = os.environ.get("MCP_CONFIG_PATH")
    if env_path:
        p = Path(env_path)
        return p if p.exists() else None
    real = _BACKEND_ROOT / "mcp_servers.yaml"
    if real.exists():
        return real
    sample = _BACKEND_ROOT / "mcp_servers.example.yaml"
    if sample.exists():
        return sample
    return None


def _expand_env(value: Any) -> Any:
    """Recursively expand ${VAR} in any string value. Fails on missing vars."""
    if isinstance(value, str):

        def _sub(m: re.Match[str]) -> str:
            var = m.group(1)
            env_val = os.environ.get(var)
            if env_val is None:
                raise MissingEnvVarError(f"MCP config references ${{{var}}} but env var is unset.")
            return env_val

        return _ENV_VAR_RE.sub(_sub, value)
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    return value


def _parse_entry(raw: dict[str, Any]) -> ServerConfig:
    name = raw.get("name")
    if not name or not isinstance(name, str):
        raise ValueError(f"MCP server entry missing `name`: {raw!r}")
    transport = raw.get("transport")
    if transport == "stdio":
        command = raw.get("command")
        if not command:
            raise ValueError(f"stdio MCP server '{name}' missing `command`")
        return StdioServerConfig(
            name=name,
            command=command,
            args=list(raw.get("args") or []),
            env=dict(raw.get("env") or {}),
        )
    if transport == "http":
        url = raw.get("url")
        if not url:
            raise ValueError(f"http MCP server '{name}' missing `url`")
        return HttpServerConfig(
            name=name,
            url=url,
            headers=dict(raw.get("headers") or {}),
        )
    raise ValueError(
        f"MCP server '{name}' has unsupported transport: {transport!r} (must be 'stdio' or 'http')"
    )


def load_config(path: Path | None = None) -> list[ServerConfig]:
    """
    Load and validate the MCP server list.

    Returns an empty list when no config file is present — the manager will
    then run with zero servers and the registry degrades gracefully.
    """
    resolved = _resolve_config_path(path)
    if resolved is None:
        log.info("MCP: no config file found; running with 0 servers")
        return []

    log.info(f"MCP: loading config from {resolved}")
    raw = yaml.safe_load(resolved.read_text(encoding="utf-8")) or {}
    expanded = _expand_env(raw)
    entries = expanded.get("servers") or []
    if not isinstance(entries, list):
        raise ValueError("MCP config: `servers` must be a list")

    configs: list[ServerConfig] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError(f"MCP config: server entry must be a mapping, got {entry!r}")
        cfg = _parse_entry(entry)
        if cfg.name in seen:
            raise ValueError(f"MCP config: duplicate server name '{cfg.name}'")
        seen.add(cfg.name)
        configs.append(cfg)

    log.info(f"MCP: {len(configs)} server(s) configured: {[c.name for c in configs]}")
    return configs
