"""`context` — show the current conversation's context-window usage.

Reads the running ``total_input_tokens`` from the conversation row (DB)
and compares to the active model's ``max_input_tokens`` from the LiteLLM
bridge. Falls back to a chars/4 approximation over ``ctx.messages`` if
the DB row can't be fetched (e.g. brand-new conversation, db-service
hiccup).

Holds both the Command definition and its ``call`` implementation. The
sibling ``__init__.py`` is a barrel-only re-export per the
``feedback_init_barrel_only`` constraint.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any, cast

from app.db import conversations

from ...types.command import Command


def _approx_chars(messages: list) -> int:
    """Best-effort char count over the message stream.

    Walks the loop-shape ``{"type": "user|assistant", "message": {...}}``,
    counting text + stringified tool inputs + tool_result text. Used only
    when the DB-stored total isn't available (new conversation, etc.).
    """
    total = 0
    for m in messages:
        if not isinstance(m, dict):
            continue
        msg = m.get("message", m)
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if isinstance(content, str):
            total += len(content)
            continue
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                total += len(block.get("text") or "")
            elif btype == "tool_use":
                total += len(str(block.get("input") or ""))
                total += len(block.get("name") or "")
            elif btype == "tool_result":
                inner = block.get("content")
                if isinstance(inner, str):
                    total += len(inner)
                elif isinstance(inner, list):
                    for sub in inner:
                        if isinstance(sub, dict) and sub.get("type") == "text":
                            total += len(sub.get("text") or "")
    return total


async def call(_args: str, ctx: Any) -> dict:
    options = getattr(ctx, "options", None)
    model = getattr(options, "mainLoopModel", "") or "unknown"
    authorization = getattr(ctx, "authorization", None)
    conversation_id = getattr(ctx, "conversation_id", None)
    messages = getattr(ctx, "messages", []) or []

    # Prefer the DB-stored running totals; fall back to an approximation
    # when the row isn't available (best-effort, never fails the command).
    input_tokens = 0
    output_tokens = 0
    source = "approximate"
    if authorization and conversation_id:
        conv = await conversations.get_conversation(authorization, conversation_id)
        if conv:
            input_tokens = int(conv.get("total_input_tokens") or 0)
            output_tokens = int(conv.get("total_output_tokens") or 0)
            source = "exact"

    if source != "exact":
        input_tokens = (_approx_chars(messages) + 3) // 4

    context_window = 0
    max_output = 0
    try:
        from app.bridges.litellm_bridge import get_all_model_info

        for info in get_all_model_info():
            if info.get("name") == model:
                context_window = int(info.get("max_input_tokens") or 0)
                max_output = int(info.get("max_output_tokens") or 0)
                break
    except Exception:  # noqa: BLE001
        pass

    if context_window > 0:
        usage_pct = min(100.0, (input_tokens / context_window) * 100)
        remaining = max(0, context_window - input_tokens)
        lines = [
            f"{usage_pct:.1f}% context used ({input_tokens:,} / {context_window:,} tokens)",
            f"Model: {model}",
            f"Remaining: {remaining:,} tokens",
        ]
        if output_tokens:
            lines.append(f"Output emitted: {output_tokens:,} tokens")
        if max_output:
            lines.append(f"Max output: {max_output:,} tokens")
        if source == "approximate":
            lines.append("(input tokens estimated — DB total unavailable)")
    else:
        lines = [
            f"~{input_tokens:,} input tokens",
            f"Model: {model} (no window info available)",
        ]

    return {"type": "value", "value": "\n".join(lines)}


async def _load():
    return import_module(__name__)


context: Command = cast(
    Command,
    {
        "type": "local",
        "execution": "server",
        "name": "context",
        "description": "Show current context-window usage",
        "aliases": [],
        "supports_non_interactive": True,
        "load": _load,
    },
)
