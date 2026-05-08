"""
Thin wrapper around `mcp.ClientSession`.

Hides two things from the rest of the service layer:
  1. Which transport a given server uses (stdio vs streamable HTTP).
  2. The MCP SDK's double-context-manager pattern — long-lived sessions are
     held open via an AsyncExitStack, and `close()` tears both down.

The wrapper exposes a small, dict-shaped surface so the rest of the code
doesn't depend on the SDK's response objects.
"""

from __future__ import annotations

import base64
from contextlib import AsyncExitStack
from typing import Any

from app_logger import get_logger

from .types import HttpServerConfig, ServerConfig, StdioServerConfig

log = get_logger(__name__)


class McpClient:
    """One logical connection to one MCP server."""

    def __init__(self, cfg: ServerConfig):
        self.cfg = cfg
        self._stack: AsyncExitStack | None = None
        self._session: Any = None  # mcp.ClientSession
        self._connected: bool = False

    @property
    def name(self) -> str:
        return self.cfg.name

    @property
    def connected(self) -> bool:
        return self._connected and self._session is not None

    async def connect(self) -> None:
        """
        Open the transport + initialize an MCP session. Raises on failure —
        the connection manager catches and records the error.
        """
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        stack = AsyncExitStack()
        try:
            if isinstance(self.cfg, StdioServerConfig):
                params = StdioServerParameters(
                    command=self.cfg.command,
                    args=list(self.cfg.args),
                    env=dict(self.cfg.env) if self.cfg.env else None,
                )
                read, write = await stack.enter_async_context(stdio_client(params))
            elif isinstance(self.cfg, HttpServerConfig):
                from mcp.client.streamable_http import streamablehttp_client
                # streamablehttp_client yields (read, write, session_id_cb)
                triple = await stack.enter_async_context(
                    streamablehttp_client(self.cfg.url, headers=self.cfg.headers or None)
                )
                read, write = triple[0], triple[1]
            else:
                raise TypeError(f"Unsupported MCP transport: {type(self.cfg).__name__}")

            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            self._stack = stack
            self._session = session
            self._connected = True
            log.info(f"MCP: connected to '{self.cfg.name}'")
        except BaseException as original:
            # anyio's task group can wrap transport failures (SSL, DNS, refused)
            # as a bare CancelledError on the awaiting task, with the real cause
            # only surfacing during `stack.aclose()`. Catch BaseException so we
            # always run the rollback, then re-raise whatever's more informative.
            try:
                await stack.aclose()
            except BaseException as teardown:
                # The teardown error typically carries the real SSL/transport
                # reason (anyio wraps the initial await in a bare CancelledError
                # and only surfaces the cause during cancel-scope unwind). Chain
                # it onto the original so _best_error_detail can find it.
                if original is not teardown:
                    original.__cause__ = teardown
            raise

    async def close(self) -> None:
        if self._stack is not None:
            try:
                await self._stack.aclose()
            except Exception as e:  # noqa: BLE001
                log.warning(f"MCP: error closing '{self.cfg.name}': {e}")
        self._stack = None
        self._session = None
        self._connected = False

    # ── API surface ─────────────────────────────────────────────────────────

    async def list_tools(self) -> list[dict[str, Any]]:
        """
        Return raw MCP tool descriptors.

        Each entry has keys: name, description, inputSchema, and optional
        annotations (e.g. {readOnlyHint: true}).
        """
        self._require_session()
        result = await self._session.list_tools()
        out: list[dict[str, Any]] = []
        for t in getattr(result, "tools", []) or []:
            out.append({
                "name": getattr(t, "name", ""),
                "description": getattr(t, "description", "") or "",
                "inputSchema": getattr(t, "inputSchema", None) or {"type": "object"},
                "annotations": _annotations_to_dict(getattr(t, "annotations", None)),
            })
        return out

    async def list_resources(self) -> list[dict[str, Any]]:
        self._require_session()
        result = await self._session.list_resources()
        out: list[dict[str, Any]] = []
        for r in getattr(result, "resources", []) or []:
            out.append({
                "uri": str(getattr(r, "uri", "")),
                "name": getattr(r, "name", "") or "",
                "description": getattr(r, "description", "") or "",
                "mimeType": getattr(r, "mimeType", None),
            })
        return out

    async def call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """
        Invoke a remote tool and flatten the result into a simple dict.

        Returns {content: str, is_error: bool, raw: list[...]} — `content` is
        the concatenation of all text blocks (good enough for most tools);
        callers that need non-text content can inspect `raw`.
        """
        self._require_session()
        result = await self._session.call_tool(name, arguments=args or {})
        text_chunks: list[str] = []
        raw_blocks: list[dict[str, Any]] = []
        for block in getattr(result, "content", []) or []:
            btype = getattr(block, "type", None)
            if btype == "text":
                text_chunks.append(getattr(block, "text", ""))
                raw_blocks.append({"type": "text", "text": getattr(block, "text", "")})
            elif btype == "image":
                raw_blocks.append({
                    "type": "image",
                    "mimeType": getattr(block, "mimeType", None),
                    "data": getattr(block, "data", ""),
                })
            else:
                # Unknown block type — preserve what we can.
                raw_blocks.append({"type": btype or "unknown", "repr": repr(block)})
        return {
            "content": "".join(text_chunks),
            "is_error": bool(getattr(result, "isError", False)),
            "raw": raw_blocks,
        }

    async def read_resource(self, uri: str) -> dict[str, Any]:
        """
        Read an MCP resource. Text payloads land in `text`; binary payloads in
        `blob_base64`.
        """
        self._require_session()
        result = await self._session.read_resource(uri)
        mime: str | None = None
        text: str | None = None
        blob_b64: str | None = None
        for item in getattr(result, "contents", []) or []:
            if mime is None:
                mime = getattr(item, "mimeType", None)
            item_text = getattr(item, "text", None)
            if item_text is not None:
                text = (text or "") + item_text
                continue
            item_blob = getattr(item, "blob", None)
            if item_blob is not None:
                if isinstance(item_blob, (bytes, bytearray)):
                    blob_b64 = base64.b64encode(bytes(item_blob)).decode("ascii")
                else:
                    blob_b64 = str(item_blob)  # SDK may already hand us base64 text
        return {"uri": uri, "mime": mime, "text": text, "blob_base64": blob_b64}

    # ── Internals ───────────────────────────────────────────────────────────

    def _require_session(self) -> None:
        if self._session is None:
            raise RuntimeError(f"MCP client '{self.cfg.name}' is not connected")


def _annotations_to_dict(ann: Any) -> dict[str, Any]:
    """MCP's annotations object → plain dict (robust to SDK shape changes)."""
    if ann is None:
        return {}
    if isinstance(ann, dict):
        return dict(ann)
    if hasattr(ann, "model_dump"):
        try:
            return ann.model_dump(exclude_none=True)
        except Exception:  # noqa: BLE001
            pass
    # Fallback: best-effort attribute pull.
    out: dict[str, Any] = {}
    for attr in ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint", "title"):
        val = getattr(ann, attr, None)
        if val is not None:
            out[attr] = val
    return out
