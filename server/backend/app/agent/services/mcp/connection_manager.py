"""
MCP connection manager — singleton pool of live MCP client sessions.

Lifecycle:
  - `start()` is called from FastAPI's lifespan on boot. It dials every
    configured server in parallel, logs failures, and caches each server's
    tool list. A failed server does not block startup.
  - Per `/turn`, `list_servers()` feeds the tool bridge so the registry
    reflects live state.
  - `ensure_connected(name)` transparently re-dials a dropped server on
    first subsequent use (with bounded retries so a flapping server
    doesn't hold up the request).
  - `shutdown()` tears down all sessions.

The manager is held in a module-global — `get_manager()` / `set_manager()`
gate access so code that imports during tests (before lifespan runs) gets
a clean RuntimeError instead of a silent None.
"""

from __future__ import annotations

import asyncio

from app_logger import get_logger

from .client import McpClient
from .types import ServerConfig, ServerStatus

log = get_logger(__name__)

# Bounds: 3 attempts over ~0.4s — good enough for transient drops, doesn't
# turn a permanent outage into a wall-clock stall on every tool call.
_RECONNECT_ATTEMPTS = 3
_RECONNECT_INITIAL_BACKOFF_S = 0.1

# Hard wall on a single connect handshake. Without this a misbehaving server
# can hold the FastAPI lifespan open indefinitely.
_CONNECT_TIMEOUT_S = 10.0


class McpConnectionManager:
    def __init__(self, configs: list[ServerConfig]):
        self._configs: list[ServerConfig] = list(configs)
        self._clients: dict[str, McpClient] = {}
        self._statuses: dict[str, ServerStatus] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        for cfg in self._configs:
            self._statuses[cfg.name] = ServerStatus(name=cfg.name, connected=False)
            self._locks[cfg.name] = asyncio.Lock()

    # ── Lifecycle ───────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Dial every configured server in parallel. Failures are logged."""
        if not self._configs:
            log.info("MCP: no servers configured; skipping startup dial")
            return
        log.info(f"MCP: dialing {len(self._configs)} server(s)")
        await asyncio.gather(
            *[self._connect_and_cache(cfg) for cfg in self._configs],
            return_exceptions=True,
        )
        live = [s for s in self._statuses.values() if s.connected]
        log.info(f"MCP: {len(live)}/{len(self._configs)} server(s) connected")

    async def shutdown(self) -> None:
        if not self._clients:
            return
        log.info(f"MCP: closing {len(self._clients)} connection(s)")
        await asyncio.gather(
            *[c.close() for c in self._clients.values()],
            return_exceptions=True,
        )
        self._clients.clear()
        for status in self._statuses.values():
            status.connected = False

    # ── Query ───────────────────────────────────────────────────────────────

    def list_servers(self) -> list[ServerStatus]:
        return list(self._statuses.values())

    def get_client(self, name: str) -> McpClient | None:
        client = self._clients.get(name)
        if client and client.connected:
            return client
        return None

    async def ensure_connected(self, name: str) -> McpClient | None:
        """
        Return a live client for `name`, reconnecting once if the session dropped.
        Returns None if the server is unknown or all reconnect attempts fail.
        """
        if name not in self._locks:
            return None
        client = self._clients.get(name)
        if client and client.connected:
            return client

        # Serialize reconnects for one server so concurrent tool calls don't
        # spawn duplicate handshakes.
        async with self._locks[name]:
            client = self._clients.get(name)
            if client and client.connected:
                return client
            cfg = next((c for c in self._configs if c.name == name), None)
            if cfg is None:
                return None
            backoff = _RECONNECT_INITIAL_BACKOFF_S
            for attempt in range(1, _RECONNECT_ATTEMPTS + 1):
                try:
                    await self._connect_and_cache(cfg)
                    if self._statuses[name].connected:
                        return self._clients.get(name)
                except BaseException as e:  # noqa: BLE001
                    log.warning(
                        f"MCP: reconnect '{name}' attempt {attempt} failed: {_best_error_detail(e)}"
                    )
                await asyncio.sleep(backoff)
                backoff *= 2
            return None

    # ── Internals ───────────────────────────────────────────────────────────

    async def _connect_and_cache(self, cfg: ServerConfig) -> None:
        """Dial one server, cache its tool list. Records failures in status."""
        # Best-effort close of a prior client for this server (e.g. reconnect).
        old = self._clients.pop(cfg.name, None)
        if old is not None:
            try:
                await old.close()
            except Exception:  # noqa: BLE001
                pass

        client = McpClient(cfg)
        try:
            await asyncio.wait_for(client.connect(), timeout=_CONNECT_TIMEOUT_S)
        # anyio's task group wraps transport failures (SSL, DNS, refused) as a
        # CancelledError on the awaiting task, with the real cause surfacing
        # only during teardown. `except Exception:` misses CancelledError (and
        # any BaseExceptionGroup with a BaseException child), so catch wide and
        # extract whatever detail we can for the log.
        except BaseException as e:  # noqa: BLE001
            detail = _best_error_detail(e)
            self._statuses[cfg.name] = ServerStatus(name=cfg.name, connected=False, error=detail)
            log.warning(f"MCP: could not connect to '{cfg.name}': {detail}")
            # Best-effort teardown if connect() left partial state.
            try:
                await client.close()
            except BaseException:  # noqa: BLE001
                pass
            return

        try:
            tools = await client.list_tools()
        except BaseException as e:  # noqa: BLE001
            log.warning(
                f"MCP: '{cfg.name}' connected but list_tools failed: {_best_error_detail(e)}"
            )
            tools = []

        self._clients[cfg.name] = client
        self._statuses[cfg.name] = ServerStatus(
            name=cfg.name, connected=True, error=None, tools=tools
        )
        log.info(f"MCP: '{cfg.name}' registered with {len(tools)} tool(s)")


def _best_error_detail(exc: BaseException) -> str:
    """
    Surface the most useful line from an anyio/task-group error chain.

    A bare CancelledError is useless in a log; the real cause is usually on
    `__cause__`/`__context__` or nested in an ExceptionGroup from teardown.
    """
    seen: set[int] = set()
    msgs: list[str] = []

    def walk(e: BaseException | None) -> None:
        if e is None or id(e) in seen:
            return
        seen.add(id(e))
        if isinstance(e, BaseExceptionGroup):
            for sub in e.exceptions:
                walk(sub)
            return
        text = f"{type(e).__name__}: {e}".strip()
        if text and text not in msgs:
            msgs.append(text)
        walk(e.__cause__)
        walk(e.__context__)

    walk(exc)

    # Rank by how useful the message is. anyio's internal plumbing leaves
    # WouldBlock / CancelledError on the chain alongside the real cause — we
    # want the transport-layer reason (SSL / DNS / Connect*) if present.
    def score(m: str) -> int:
        low = m.lower()
        if any(k in low for k in ("ssl", "certificate", "tls")):
            return 3
        if any(
            k in low
            for k in ("connecterror", "connectionrefused", "getaddrinfo", "name or service")
        ):
            return 2
        if m.startswith(("CancelledError", "WouldBlock")):
            return 0
        return 1

    if not msgs:
        return repr(exc)
    return max(msgs, key=score)


# ── Module-global accessor ──────────────────────────────────────────────────

_manager: McpConnectionManager | None = None


def set_manager(m: McpConnectionManager | None) -> None:
    global _manager
    _manager = m


def get_manager() -> McpConnectionManager:
    """Return the live manager. Raises RuntimeError if not yet initialized."""
    if _manager is None:
        raise RuntimeError("McpConnectionManager is not initialized")
    return _manager


def maybe_get_manager() -> McpConnectionManager | None:
    """Non-raising variant for optional integrations (registry, system prompt)."""
    return _manager
