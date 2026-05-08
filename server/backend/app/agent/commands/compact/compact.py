"""`compact` — manually fire compaction.

Source: src/commands/compact/index.ts.

The local command body invokes ``compact_conversation(manual=True)``
on the conversation history carried by the input-time
``ToolUseContext`` (the temporary one the router builds before
QueryEngine assembly). On success it persists a typed
``compact_boundary`` marker row to the conversation so future turns
load only the post-boundary slice, and returns a
``LOCAL_COMMAND_STDOUT_TAG``-shaped value summarising the result so
chat-ui can render the stdout bubble alongside the inline divider.

Persistence model (replaces the original "preview-only" behaviour)
------------------------------------------------------------------
The conversation's ``messages`` table is strictly append-only. We
honour that by writing one new row::

    role     = "system"
    content  = [{"type": "compact_boundary", "summary": "...", ...}]

``agent/router.py::_build_turn_messages`` calls
``apply_boundary_filter`` after loading history; that filter finds
the latest boundary marker and returns
``[<synthesised user-shape summary>, *post_boundary_rows]`` to the
agent loop, so the model never re-reads the dropped slice.

Failure mode: persistence errors do NOT mask the compaction itself —
the summary still surfaces to the user and the divider still renders
mid-session. We log the persistence failure so the next turn's
re-load will redo the work; the user sees no broken state, just a
single missed in-place reduction.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any, cast

from app_logger import get_logger

from app.bridges import db_client

from ...types.command import Command
from ...utils.compact_boundary_marker import make_boundary_payload

log = get_logger(__name__)


async def _persist_boundary(ctx: Any, boundary: Any) -> None:
    """Write the boundary marker to ``messages``. Best-effort.

    Pulls ``authorization`` and ``conversation_id`` off ``ctx`` (the
    input-time ``ToolUseContext`` built by the router). If either is
    missing — e.g. a unit test calling /compact with a stub ctx — we
    skip persistence quietly; the in-session summary preview still
    works. Network errors are logged, not raised: a persistence hiccup
    must not turn a successful compaction into a user-visible failure.
    """
    authorization = getattr(ctx, "authorization", None)
    conversation_id = getattr(ctx, "conversation_id", None)
    if not authorization or not conversation_id:
        log.warning(
            "/compact: ctx missing authorization or conversation_id; "
            "boundary not persisted (in-session preview only)"
        )
        return
    try:
        await db_client.append_message(
            authorization,
            str(conversation_id),
            role="system",
            content=make_boundary_payload(boundary),
        )
    except Exception as e:  # noqa: BLE001
        log.exception(
            "/compact: failed to persist boundary for conv=%s: %s",
            conversation_id, e,
        )


async def call(args: str, ctx: Any) -> dict:
    """Run a manual compaction pass and persist the boundary.

    Reads ``ctx.messages`` (populated by the router's input-time
    ``ToolUseContext``), invokes ``compact_conversation`` with
    ``manual=True``, persists the resulting boundary marker so the
    next turn loads only the post-boundary slice, and returns a
    ``value``-typed result containing the human-readable summary +
    counts.

    Errors in the compaction itself are caught and returned as a
    value (not raised) — a ``/compact`` failure shouldn't crash the
    user's turn; surface the failure as a readable message.
    Persistence failures are logged and otherwise swallowed; the
    summary still surfaces to the user.
    """
    # Late imports keep the command module cheap to import — compaction
    # touches the LLM provider stack which has its own import cost.
    from ...services.compact.compact import compact_conversation  # noqa: PLC0415

    messages = []
    if ctx is not None:
        messages = list(getattr(ctx, "messages", []) or [])

    if not messages:
        return {
            "type": "value",
            "value": "Nothing to compact — the conversation has no messages yet.",
        }

    try:
        result = await compact_conversation(messages, ctx, manual=True)
    except Exception as e:  # noqa: BLE001
        log.exception("/compact failed: %s", e)
        return {
            "type": "value",
            "value": f"Compaction failed: {e}",
        }

    if result.skipped:
        return {
            "type": "value",
            "value": (
                "Conversation is too short to usefully compact — "
                "nothing to summarize."
            ),
        }

    if result.boundary is not None:
        await _persist_boundary(ctx, result.boundary)

    saved = max(0, result.tokens_before - result.tokens_after)
    summary_preview = result.summary.strip()
    if len(summary_preview) > 600:
        summary_preview = summary_preview[:600].rstrip() + "..."

    body = (
        f"**Compacted** {result.dropped_count} earlier message"
        f"{'s' if result.dropped_count != 1 else ''} into a summary.\n\n"
        f"- Tokens before: ~{result.tokens_before:,}\n"
        f"- Tokens after:  ~{result.tokens_after:,}\n"
        f"- Tokens saved:  ~{saved:,}\n\n"
        f"**Summary preview:**\n\n{summary_preview}\n\n"
        f"_From the next turn onward, the model will read this summary "
        f"in place of the earlier history. The full conversation is "
        f"preserved in your project for reference._"
    )

    return {"type": "value", "value": body}


async def _load():
    return import_module(__name__)


compact: Command = cast(Command, {
    "type": "local",
    "execution": "server",
    "name": "compact",
    "description": "Summarize earlier conversation history (manual)",
    "aliases": [],
    "supports_non_interactive": True,
    # No longer hidden — Phase 3.2 makes /compact functional.
    "is_hidden": False,
    "load": _load,
})
