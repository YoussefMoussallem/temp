"""Turn-local helpers: message shape, options translation, persistence retry,
orphan-pair diagnostics.

All functions here are used exclusively by the /turn endpoint cluster
(``endpoint.py`` and ``messages.py``). They live in this module to keep
the endpoint and message-building modules readable; promoting any to
``agent/utils/`` would scatter related code for no gain.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from app.bridges import app_settings_client, db_client
from app_logger import get_logger

from ...types.permissions import PermissionAllowDecision

if TYPE_CHECKING:
    from .schemas import AgentTurnRequest

log = get_logger(__name__)


async def _allow_all(_name: str, _input: dict) -> PermissionAllowDecision:
    """v1 permission gate — allows everything. Phase 4 wires real engine."""
    return PermissionAllowDecision(behavior="allow")


def _wrap(role: str, content: Any) -> dict:
    """Wrap a {role, content} pair in the loop's message dict format."""
    return {"type": role, "message": {"role": role, "content": content}}


def _db_row_to_loop_message(row: dict) -> dict:
    """Translate a db-service message row to the loop's message dict format."""
    return _wrap(row["role"], row["content"])


def _tool_results_blocks(body: "AgentTurnRequest") -> list[dict] | None:
    """Convert frontend tool_results payload to tool_result content blocks."""
    if not body.tool_results:
        return None
    return [
        {
            "type": "tool_result",
            "tool_use_id": tr.call_id,
            "content": tr.output,
            "is_error": not tr.success,
        }
        for tr in body.tool_results
    ]


def _as_storable_content(content: Any) -> list[dict]:
    """Normalize loop content (str or list of blocks) to a JSON-storable list."""
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return list(content or [])


def qe_options_for_input(
    body: "AgentTurnRequest",
    models: app_settings_client.ModelDefaults,
):
    """Build a minimal ToolUseContextOptions for the pre-loop input pass
    (slash dispatch + plain passthrough). Doesn't set permissionMode —
    that happens inside QueryEngine.run.

    Model ids come from the resolved admin defaults rather than the
    request body — the frontend no longer chooses them.
    """
    from ...Tool import ToolUseContextOptions

    opts = ToolUseContextOptions()
    opts.mainLoopModel = models.default_model
    opts.searchModel = models.search_model
    opts.thinking = body.thinking
    return opts


def _image_attachments(body: "AgentTurnRequest") -> list[dict]:
    """Convert ImagePayload list into Anthropic-shape image content blocks."""
    if not body.images:
        return []
    return [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": img.mime_type,
                "data": img.base64,
            },
        }
        for img in body.images
    ]


def _count_orphan_tool_pairs(messages: list[dict]) -> tuple[int, int]:
    """Count tool_use blocks without a matching tool_result and vice versa.

    Used purely for diagnostics — the actual repair is delegated to
    ``post_compact_cleanup``. We compute this separately so we can log
    *that* a repair happened (and roughly what shape) without making the
    cleanup pass itself I/O-aware.

    Returns ``(orphan_uses, orphan_results)``.
    """
    uses: set[str] = set()
    results: set[str] = set()
    for msg in messages:
        inner = msg.get("message") if isinstance(msg, dict) else None
        if not isinstance(inner, dict):
            continue
        content = inner.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "tool_use":
                tid = block.get("id")
                if isinstance(tid, str):
                    uses.add(tid)
            elif btype == "tool_result":
                tid = block.get("tool_use_id")
                if isinstance(tid, str):
                    results.add(tid)
    return len(uses - results), len(results - uses)


async def _append_with_retry(
    authorization: str,
    conversation_id: str,
    *,
    role: str,
    content: list[dict],
    attempts: int = 3,
) -> dict | None:
    """Persist a message, retrying on transient failure with exponential backoff."""
    backoff = 0.2
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await db_client.append_message(
                authorization, conversation_id, role=role, content=content
            )
        except Exception as e:  # noqa: BLE001
            last_exc = e
            log.warning(
                f"append_message attempt {attempt}/{attempts} failed for "
                f"conv={conversation_id}: {e}"
            )
            if attempt < attempts:
                await asyncio.sleep(backoff)
                backoff *= 2
    log.error(
        f"append_message gave up after {attempts} attempts for conv={conversation_id}: {last_exc}"
    )
    return None
