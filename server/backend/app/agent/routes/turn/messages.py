"""Turn pre-loop: load history, persist new inbound, process user input.

The pre-loop phase of a /turn does three things in order:
  1. Pull prior history from db-service.
  2. Persist any tool_result blocks the frontend sent back, then append
     them to the in-memory message list (they respond to the *prior*
     assistant turn's tool_use blocks, so they go before fresh input).
  3. Run user_input through process_user_input — which may emit
     multiple user-shape messages, may short-circuit (local slash
     command, no model call needed), and may queue a command_uuid
     for the loop's lifecycle hooks.

``_build_turn_messages`` returns a tagged result rather than yielding
SSE itself so the streaming layer in ``endpoint.py`` stays the only
place that touches the wire format.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.bridges import app_settings_client, db_client
from app_logger import get_logger

from ...services.compact.post_compact_cleanup import post_compact_cleanup
from ...Tool import ToolUseContext
from ...utils.compact_boundary_marker import apply_boundary_filter
from ...utils.process_user_input import process_user_input
from ...utils.slash_command_parsing import is_slash_command
from .helpers import (
    _append_with_retry,
    _as_storable_content,
    _count_orphan_tool_pairs,
    _db_row_to_loop_message,
    _image_attachments,
    _tool_results_blocks,
    _wrap,
    qe_options_for_input,
)
from .schemas import AgentTurnRequest

log = get_logger(__name__)


@dataclass
class _MessagesBuilt:
    """Inbound persisted, history loaded — caller proceeds to the LLM loop."""

    messages: list[dict]
    command_uuids: list[str]


@dataclass
class _MessagesShortCircuit:
    """Local slash-command resolved without a model call.

    The processed messages are already persisted; the caller just needs
    to surface them to the wire and emit lifecycle/done events.
    """

    processed_messages: list[dict]
    command_uuid: str | None


@dataclass
class _MessagesError:
    """Persistence or input processing failed; surface as SSE `error`."""

    message: str


_BuildTurnMessagesResult = _MessagesBuilt | _MessagesShortCircuit | _MessagesError


async def _build_turn_messages(
    body: AgentTurnRequest,
    authorization: str,
    models: app_settings_client.ModelDefaults,
) -> _BuildTurnMessagesResult:
    """Load history, persist new inbound, process user input.

    Side effects: writes to db-service. We intentionally persist *before*
    calling the LLM so inbound state survives a backend crash mid-stream.
    Persistence failures are returned as ``_MessagesError`` rather than
    raised — the caller is the SSE layer and needs to translate them.
    """
    try:
        history_rows = await db_client.get_messages(authorization, body.conversation_id)
    except Exception as e:  # noqa: BLE001
        log.error(f"Failed to load conversation {body.conversation_id}: {e}")
        return _MessagesError(f"Could not load conversation: {e}")

    # Apply the latest compact boundary (if any) before handing to the
    # loop. The UI continues to render the unfiltered list (audit
    # trail + visual continuity); this filter is the LLM-facing view
    # only. See ``utils/compact_boundary_marker.py`` for the semantics.
    history_rows_for_llm = apply_boundary_filter(history_rows)
    if len(history_rows_for_llm) != len(history_rows):
        log.info(
            "compact boundary applied: %d row(s) collapsed into summary, %d row(s) post-boundary",
            len(history_rows) - len(history_rows_for_llm),
            len(history_rows_for_llm) - 1,  # subtract the synthesised summary itself
        )

    messages: list[dict] = [_db_row_to_loop_message(r) for r in history_rows_for_llm]

    tool_result_blocks = _tool_results_blocks(body)
    if tool_result_blocks:
        persisted = await _append_with_retry(
            authorization,
            body.conversation_id,
            role="user",
            content=tool_result_blocks,
        )
        if persisted is None:
            return _MessagesError("Failed to persist tool results")
        messages.append(_wrap("user", tool_result_blocks))

    command_uuids: list[str] = []

    if body.user_input:
        try:
            tmp_ctx = ToolUseContext(
                options=qe_options_for_input(body, models),
                messages=messages,
                authorization=authorization,
                project_id=body.project_id,
                conversation_id=body.conversation_id,
            )
            processed = await process_user_input(
                body.user_input,
                tmp_ctx,
                attachments=_image_attachments(body),
            )
        except Exception as e:  # noqa: BLE001
            log.exception(f"process_user_input failed: {e}")
            return _MessagesError(f"Input processing failed: {e}")

        # process_user_input only ever emits user-shape messages —
        # tool_result blocks were already persisted above.
        for msg in processed.messages:
            msg_content = msg.get("message", {}).get("content")
            storable = _as_storable_content(msg_content)
            if not storable:
                continue
            persisted = await _append_with_retry(
                authorization,
                body.conversation_id,
                role="user",
                content=storable,
            )
            if persisted is None:
                return _MessagesError("Failed to persist input message")
            messages.append(msg)

        if not processed.should_query:
            return _MessagesShortCircuit(
                processed_messages=list(processed.messages),
                command_uuid=body.command_uuid,
            )

        # Slash-command prompt-type expansion — queue the uuid so
        # query() fires lifecycle. Plain text passthrough has no uuid.
        if is_slash_command(body.user_input) and body.command_uuid:
            command_uuids.append(body.command_uuid)

    # Defensive pair-repair before the LLM sees the message list.
    #
    # The Anthropic / Bedrock API strict-validates that every tool_use
    # block in an assistant message has a matching tool_result block in
    # the next user message. Edwin can violate that invariant in two
    # ways even on a healthy code path:
    #
    #   1. A partial-write — assistant tool_use persisted, but the
    #      matching user tool_result append failed (db-service 5xx,
    #      network blip). _append_with_retry gives up after 3 attempts
    #      and the conversation is left structurally broken; without
    #      repair it 400s on every subsequent /turn.
    #   2. A stale frontend retry — chat-ui sends back a tool_result
    #      whose tool_use_id no longer exists in history (e.g. the
    #      assistant message was rolled back, or the client raced).
    #
    # post_compact_cleanup already implements exactly this repair (it
    # was written for the autoCompact split-point case); it's
    # idempotent and O(blocks). Running it unconditionally on every
    # turn means a single transient db-service failure can't
    # permanently brick a conversation, and stale frontend payloads
    # get filtered before they reach the wire. The cleanup also
    # strips thinking blocks and stale cache_control — both safe on
    # a re-loaded history (we don't replay prior-turn thinking, and
    # cache markers from the previous prefix shape are no longer
    # valid anyway).
    orphan_uses, orphan_results = _count_orphan_tool_pairs(messages)
    if orphan_uses or orphan_results:
        before = len(messages)
        messages = post_compact_cleanup(messages)
        log.warning(
            "pre-LLM pair-repair: dropped %d orphan tool_use(s) and "
            "%d orphan tool_result(s) for conv=%s (messages: %d → %d). "
            "Likely a partial-write from a prior /turn.",
            orphan_uses,
            orphan_results,
            body.conversation_id,
            before,
            len(messages),
        )

    return _MessagesBuilt(messages=messages, command_uuids=command_uuids)
