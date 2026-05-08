"""
Tool-result budget — disk-spill for oversized tool_result blocks.

Source: src/utils/toolResultStorage.ts.

Replaces the lossy ``maxResultSizeChars`` truncate with a lossless
disk-spill: tool_result content above the threshold gets written to
``<cwd>/.edwin/tool_results/[<conversation_id>/]<tool_use_id>.txt``,
and the in-message content is rewritten to a marker that includes
the disk path, the original size, and a short preview.

Why this is *not* deferred (unlike microcompact / apply_collapses):

  - The disk-spill is **lossless** — full content survives on disk and
    can be inspected by ops/dev or rehydrated by a future Read tool.
  - The savings don't depend on prompt caching — tokens drop on the
    wire whether or not the prefix is cached.
  - It replaces existing lossy behaviour (the per-tool
    ``maxResultSizeChars`` cap), so this is strictly an upgrade.

Idempotency: a message that already carries a spill-marker is left
untouched. Pipeline runs every turn; without idempotency we'd
re-spill the same content repeatedly. With it, the second-and-later
runs are O(scan).

Failure mode: any exception from the disk write (permissions, disk
full, path issues on Windows) falls back to an in-memory truncate +
warning log. A storage hiccup must NEVER crash the user's turn.

Storage layout::

  <STORAGE_DIR>/[<conversation_id>/]<tool_use_id>.txt

When ``ctx.conversation_id`` is available, files are scoped under a
per-conversation subdirectory so cleanup-by-conversation is a single
``rm -rf``. Without conversation_id (e.g. tests), files land flat
under ``STORAGE_DIR``.

Configuration (env vars):

  - ``EDWIN_TOOL_RESULT_THRESHOLD_CHARS``  — int, default 10000
  - ``EDWIN_TOOL_RESULT_STORAGE_DIR``      — path, default ``<cwd>/.edwin/tool_results``
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, Mapping

from app_logger import get_logger

log = get_logger(__name__)


# ── Configuration ─────────────────────────────────────────────────────────


# 10K chars ≈ 2.5K tokens. Picked to catch typical web-search / MCP-tool
# bloat without spilling small slide-tool results. Env-overridable so a
# noisy MCP integration can lower it without code changes.
# # TUNE: source-parity unknown; source uses 50K but Edwin's slide
# tools rarely emit anything close to that.
_DEFAULT_THRESHOLD_CHARS = 10_000

# Plan said ``<cwd>/.slides/``; we use ``.edwin`` to match the rest of
# the project's naming (skills live under ``~/.edwin/skills``, etc.).
_DEFAULT_STORAGE_DIR_REL = ".edwin/tool_results"

# Marker prefix on rewritten in-message content. Stable so idempotency
# works across turns. Every spilled block's content starts with this.
_MARKER_PREFIX = "[edwin:spilled-tool-result]"

# Preview cap inside the marker — enough that the LLM sees what kind
# of content was spilled, not so much that we re-bloat the message.
_PREVIEW_CHAR_CAP = 200


def _read_threshold() -> int:
    raw = os.environ.get("EDWIN_TOOL_RESULT_THRESHOLD_CHARS")
    if raw:
        try:
            # Floor at 1000 — a threshold below this would spill almost
            # every tool_result and produce more disk I/O than the
            # token savings justify.
            return max(1_000, int(raw))
        except ValueError:
            log.warning(
                "EDWIN_TOOL_RESULT_THRESHOLD_CHARS=%r not an int; using default %d",
                raw, _DEFAULT_THRESHOLD_CHARS,
            )
    return _DEFAULT_THRESHOLD_CHARS


def _read_storage_dir() -> Path:
    raw = os.environ.get("EDWIN_TOOL_RESULT_STORAGE_DIR")
    if raw:
        return Path(raw)
    return Path.cwd() / _DEFAULT_STORAGE_DIR_REL


# ── Helpers ───────────────────────────────────────────────────────────────


def _is_marker(content: Any) -> bool:
    """True if the content is already a spill-marker (idempotency check)."""
    return isinstance(content, str) and content.startswith(_MARKER_PREFIX)


def _content_to_string(content: Any) -> str:
    """Coerce tool_result.content (str | list[block] | other) to a single
    string for size-measurement and disk storage. Lossy at the *block*
    level (non-text blocks lose structure) but lossless at the *char*
    level for the dominant text-content case."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for b in content:
            if isinstance(b, Mapping) and b.get("type") == "text":
                parts.append(str(b.get("text") or ""))
            else:
                # Non-text nested block (image, embedded tool_use). Stringify
                # rather than drop — preserves *some* signal in the spill
                # file for debugging.
                parts.append(str(b))
        return "".join(parts)
    if content is None:
        return ""
    return str(content)


def _build_marker(*, tool_use_id: str, path: Path, size: int, preview: str) -> str:
    """The in-message replacement string. Format:

        [edwin:spilled-tool-result] tool_use_id=<id> path=<path> size=<n>

        Preview: <first 200 chars, single-line>

        (Full content stored at <path>.)
    """
    snippet = preview[:_PREVIEW_CHAR_CAP].replace("\n", " ").strip()
    if len(preview) > _PREVIEW_CHAR_CAP:
        snippet += "..."
    return (
        f"{_MARKER_PREFIX} tool_use_id={tool_use_id} "
        f"path={path} size={size}\n\n"
        f"Preview: {snippet}\n\n"
        f"(Full content stored at {path}.)"
    )


def _spill_to_disk_sync(path: Path, content: str) -> None:
    """Write ``content`` to ``path``. Sync — wrap with ``asyncio.to_thread``
    in async callers. Truncate-overwrite (idempotent for same-content)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _resolve_spill_path(
    storage_dir: Path, conversation_id: str | None, tool_use_id: str,
) -> Path:
    """Per-conversation subdirectory when conversation_id is available;
    flat layout otherwise. Sanitizes ``tool_use_id`` defensively — even
    though tool_use_ids are server-generated UUIDs, treating them as
    filename input means we strip path separators belt-and-braces."""
    safe_id = tool_use_id.replace("/", "_").replace("\\", "_") or "unknown"
    base = storage_dir / str(conversation_id) if conversation_id else storage_dir
    return base / f"{safe_id}.txt"


# ── Per-block / per-message rewrite ───────────────────────────────────────


async def _maybe_spill_block(
    block: Any,
    *,
    threshold: int,
    storage_dir: Path,
    conversation_id: str | None,
) -> Any:
    """Return the (possibly rewritten) block. None of:
      - non-tool_result blocks
      - tool_result blocks already carrying a marker
      - tool_result blocks under the threshold
    are touched."""
    if not isinstance(block, Mapping) or block.get("type") != "tool_result":
        return block

    body = block.get("content")
    body_str = _content_to_string(body)

    if _is_marker(body_str) or len(body_str) <= threshold:
        return block

    tool_use_id = str(block.get("tool_use_id") or "unknown")
    path = _resolve_spill_path(storage_dir, conversation_id, tool_use_id)

    try:
        await asyncio.to_thread(_spill_to_disk_sync, path, body_str)
    except Exception as e:  # noqa: BLE001
        # Disk write failed — fall back to in-memory truncation rather
        # than crashing the turn. The truncation is lossy but bounded
        # in size; the warning lets ops know storage isn't healthy.
        log.warning(
            "tool_result_storage: spill failed tool_use_id=%s path=%s err=%s "
            "(falling back to in-memory truncate)",
            tool_use_id, path, e,
        )
        truncated = body_str[:threshold] + (
            f"\n\n[Truncated. Original size: {len(body_str)} chars. "
            f"Disk spill failed: {e}]"
        )
        return {**block, "content": truncated}

    marker = _build_marker(
        tool_use_id=tool_use_id, path=path, size=len(body_str), preview=body_str,
    )
    return {**block, "content": marker}


async def _maybe_spill_message(
    msg: Any,
    *,
    threshold: int,
    storage_dir: Path,
    conversation_id: str | None,
) -> Any:
    """Walk one message's content blocks; rewrite oversized tool_results.
    Identity-return when nothing changed (avoids unnecessary copies)."""
    if not isinstance(msg, Mapping):
        return msg
    inner = msg.get("message")
    if not isinstance(inner, Mapping):
        return msg
    content = inner.get("content")
    if not isinstance(content, list):
        return msg

    new_content: list[Any] = []
    changed = False
    for block in content:
        new_block = await _maybe_spill_block(
            block,
            threshold=threshold,
            storage_dir=storage_dir,
            conversation_id=conversation_id,
        )
        if new_block is not block:
            changed = True
        new_content.append(new_block)

    if not changed:
        return msg
    return {**msg, "message": {**inner, "content": new_content}}


# ── Public entrypoint ─────────────────────────────────────────────────────


async def apply_tool_result_budget(
    messages: list[Any],
    ctx: Any = None,
) -> list[Any]:
    """Walk ``messages``; for every tool_result block whose content is
    larger than the threshold, spill the full content to disk and
    replace the in-message content with a marker.

    Idempotent: messages already carrying a spill-marker pass through
    untouched. Safe to call every turn (the pipeline does).

    Args:
      messages: pipeline-stage input. Loop-shape: each msg is a dict
        with ``type`` and optional ``message: {role, content}``.
      ctx: ``ToolUseContext`` — read for ``conversation_id`` to scope
        the spill directory. None in tests.

    Returns:
      A new list of messages with oversized blocks rewritten. Input
      list is not mutated; messages without oversized blocks are
      returned by reference (no copy).
    """
    threshold = _read_threshold()
    storage_dir = _read_storage_dir()

    conversation_id: str | None = None
    if ctx is not None:
        cid = getattr(ctx, "conversation_id", None)
        if isinstance(cid, str) and cid:
            conversation_id = cid

    out: list[Any] = []
    for msg in messages:
        new_msg = await _maybe_spill_message(
            msg,
            threshold=threshold,
            storage_dir=storage_dir,
            conversation_id=conversation_id,
        )
        out.append(new_msg)
    return out


__all__ = ["apply_tool_result_budget"]
