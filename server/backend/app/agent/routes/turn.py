"""POST /agent/turn — the agentic loop endpoint.

Stateless: each /turn request creates a fresh QueryEngine, hydrates the
opaque ClientState from the request body, runs the loop, ships state out
via the ``state_update`` SSE event. No server-side session tracking.

Phase 1.5: the basic /turn endpoint. /compact, /context, /usage stubs
live in ``routes/meta.py``.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any, AsyncIterator

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.bridges import app_settings_client, db_client
from app.bridges.litellm_bridge import calculate_cost
from app.dependencies import CurrentUser, get_current_user
from app.middleware.rate_limit import limiter, user_or_ip_key
from app_logger import get_logger

from ..QueryEngine import ClientState, QueryEngine
from ..query.transitions import Terminal
from ..services.compact.post_compact_cleanup import post_compact_cleanup
from ..Tool import Tools, ToolUseContext
from ..tools_registry import get_all_base_tools
from ..types.permissions import PermissionAllowDecision
from ..utils.command_lifecycle import (
    reset_command_lifecycle_listener,
    set_command_lifecycle_listener,
)
from ..utils.compact_boundary_marker import (
    apply_boundary_filter,
    make_boundary_payload,
)
from ..utils.process_user_input import process_user_input
from ..utils.slash_command_parsing import is_slash_command
from ._shared import _sse

log = get_logger(__name__)

router = APIRouter(tags=["agent"])


# ============================================================================
# Request schema
# ============================================================================


class ToolResultPayload(BaseModel):
    """Result from a frontend-executed tool, sent back via next /turn."""

    call_id: str
    name: str = ""
    output: str = ""
    success: bool = True


class ImagePayload(BaseModel):
    mime_type: str
    base64: str


class AgentTurnRequest(BaseModel):
    """
    /turn request body.

    Message history is loaded from db-service using ``conversation_id`` — the
    frontend no longer round-trips the message array. ClientState (agent
    todos, plan mode) is still round-tripped (not persisted in this phase).

    Model selection is admin-managed: the main-loop and search models are
    resolved per-turn from ``app_settings`` (db-service) via
    ``app_settings_client.resolve``. The frontend no longer chooses them.
    """

    conversation_id: str
    # Optional this phase — frontend starts sending it when slide tools ship.
    # Slide tools raise a clear error when invoked with project_id unset.
    project_id: str | None = None
    thinking: bool = False
    web_search: bool = True
    agent_state: dict = Field(default_factory=dict)
    user_input: str | None = None
    tool_results: list[ToolResultPayload] | None = None
    images: list[ImagePayload] | None = None
    # Slash-command uuid: when user_input begins with '/', the frontend mints
    # a uuid once at Enter-press and the backend expands the command + emits
    # command_lifecycle (started/completed) SSE events keyed on it.
    command_uuid: str | None = None


# ============================================================================
# Helpers (turn-local)
# ============================================================================


async def _allow_all(_name: str, _input: dict) -> PermissionAllowDecision:
    """v1 permission gate — allows everything. Phase 4 wires real engine."""
    return PermissionAllowDecision(behavior="allow")


def _wrap(role: str, content: Any) -> dict:
    """Wrap a {role, content} pair in the loop's message dict format."""
    return {"type": role, "message": {"role": role, "content": content}}


def _db_row_to_loop_message(row: dict) -> dict:
    """Translate a db-service message row to the loop's message dict format."""
    return _wrap(row["role"], row["content"])


def _tool_results_blocks(body: AgentTurnRequest) -> list[dict] | None:
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
    from ..Tool import ToolUseContextOptions

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


# ============================================================================
# Turn input → message list (extracted from _stream_turn)
# ============================================================================
#
# The pre-loop phase of a /turn does three things in order:
#   1. Pull prior history from db-service.
#   2. Persist any tool_result blocks the frontend sent back, then append
#      them to the in-memory message list (they respond to the *prior*
#      assistant turn's tool_use blocks, so they go before fresh input).
#   3. Run user_input through process_user_input — which may emit
#      multiple user-shape messages, may short-circuit (local slash
#      command, no model call needed), and may queue a command_uuid
#      for the loop's lifecycle hooks.
#
# That whole block lives below in `_build_turn_messages`. It returns a
# tagged result rather than yielding SSE itself so the streaming layer
# stays the only place that touches the wire format.


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


# ============================================================================
# /turn — the main agent endpoint
# ============================================================================


@router.post("/turn")
# Per-route stricter cap on top of the dual-axis global defaults
# (``app.middleware.rate_limit``). 60/min/user is one chat turn per
# second sustained — far above interactive use (~5–10 turns/min) but
# stops a runaway client locking up an LLM stream slot. Keyed per
# user so corporate NATs sharing one IP don't starve each other.
@limiter.limit("60/minute", key_func=user_or_ip_key)
async def agent_turn(
    request: Request,
    body: AgentTurnRequest,
    authorization: str | None = Header(default=None),
    user: CurrentUser = Depends(get_current_user),
):
    """
    Run one agent turn. Streams Server-Sent Events back.

    Event types:
      - stream_start: turn beginning
      - text_delta {text}: assistant text chunk
      - thinking_delta {text}: thinking block chunk
      - tool_call_start {id, name}: model started emitting tool_use block
      - tool_call_done {id, name, input}: model finished emitting tool_use block
      - tool_call_complete {call_id, name, success}: tool execution finished
      - assistant_message {message}: full assistant message after streaming
      - state_update {state}: opaque ClientState blob to round-trip
      - tool_request {parallel_calls, ...}: frontend tools to execute
      - done {reason}: turn complete
      - error {message}: fatal error
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    return StreamingResponse(
        _stream_turn(body, user, authorization),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


async def _stream_turn(
    body: AgentTurnRequest,
    user: CurrentUser,
    authorization: str,
) -> AsyncIterator[str]:
    """Generator that yields SSE-formatted events from one /turn invocation."""
    try:
        # Resolve admin-managed model defaults once per turn. Cached
        # for ~60s in-process so this is cheap on the hot path; on
        # cache miss it costs one db-service round-trip. Failures
        # degrade to env defaults — see ``app_settings_client``.
        models = await app_settings_client.resolve(authorization)

        # ── 1+2. Load history, persist inbound, process user_input. ──
        # All the pre-LLM message wrangling lives in _build_turn_messages;
        # we only translate its three possible outcomes into SSE here.
        built = await _build_turn_messages(body, authorization, models)
        if isinstance(built, _MessagesError):
            yield _sse("error", {"message": built.message})
            return
        if isinstance(built, _MessagesShortCircuit):
            # Local command — no model call. Surface the expansion to the
            # client so it can render the command output, then terminal.
            if built.command_uuid:
                yield _sse(
                    "command_lifecycle",
                    {"uuid": built.command_uuid, "state": "started"},
                )
            for msg in built.processed_messages:
                yield _sse("user_message", {"message": msg.get("message", {})})
            if built.command_uuid:
                yield _sse(
                    "command_lifecycle",
                    {"uuid": built.command_uuid, "state": "completed"},
                )
            yield _sse("done", {"stop_reason": "local_command", "usage": None})
            return

        messages = built.messages
        command_uuids_for_loop = built.command_uuids

        # ── 3. Hydrate ClientState and assemble the QueryEngine. ──
        try:
            cs = ClientState(
                **{
                    k: v
                    for k, v in body.agent_state.items()
                    if k in ClientState.__dataclass_fields__
                }
            )
        except Exception:
            cs = ClientState()

        base_tools = get_all_base_tools()
        if not body.web_search:
            base_tools = Tools(tools=[t for t in base_tools if t.name != "WebSearch"])

        qe = QueryEngine(client_state=cs, tools=base_tools)
        qe.options.mainLoopModel = models.default_model
        qe.options.searchModel = models.search_model
        qe.options.thinking = body.thinking

        tool_res_count = len(body.tool_results) if body.tool_results else 0
        log.info(
            f"agent_turn user={user.user_id} model={models.default_model} "
            f"conv={body.conversation_id} msgs={len(messages)} "
            f"tool_results={tool_res_count} user_input={bool(body.user_input)} "
            f"thinking={body.thinking} web_search={body.web_search}"
        )

        usage: dict = {}
        # Collected loop events we need to persist after the stream ends.
        to_persist: list[tuple[str, list[dict]]] = []  # (role, content) pairs

        # Lifecycle events fire synchronously from inside query()'s started/
        # finally hooks. Queue them and flush alongside the main stream so
        # order is preserved relative to other SSE events.
        lifecycle_queue: list[dict] = []

        def _lifecycle_listener(uuid: str, state: str) -> None:
            lifecycle_queue.append({"uuid": uuid, "state": state})

        lifecycle_token = set_command_lifecycle_listener(_lifecycle_listener)

        def _drain_lifecycle() -> list[str]:
            out: list[str] = []
            while lifecycle_queue:
                ev = lifecycle_queue.pop(0)
                out.append(_sse("command_lifecycle", ev))
            return out

        try:
            # ── 4. Drive the loop, translate events, capture durable messages. ──
            async for event in qe.run(
                messages=messages,
                can_use_tool=_allow_all,
                authorization=authorization,
                project_id=body.project_id,
                user_id=user.user_id,
                command_uuids=command_uuids_for_loop or None,
            ):
                # Flush any command_lifecycle events accumulated since last yield.
                for frame in _drain_lifecycle():
                    yield frame
                if isinstance(event, Terminal):
                    yield _sse("done", {"stop_reason": event.reason, "usage": usage or None})
                elif isinstance(event, dict):
                    etype = event.get("type", "unknown")
                    if etype == "stream_request_start":
                        yield _sse("stream_start", {})
                    elif etype == "text_delta":
                        yield _sse("text_delta", {"text": event.get("text", "")})
                    elif etype == "thinking_delta":
                        yield _sse("thinking_delta", {"text": event.get("text", "")})
                    elif etype == "tool_call_start":
                        yield _sse(
                            "tool_call_start", {k: v for k, v in event.items() if k != "type"}
                        )
                    elif etype == "tool_call_done":
                        yield _sse(
                            "tool_call_done", {k: v for k, v in event.items() if k != "type"}
                        )
                    elif etype == "tool_call_complete":
                        # Emitted by ``_execute_single_tool`` exactly once per
                        # backend tool call, after the tool's execution has
                        # finished (success or error). The FE seals the
                        # tool's spinner when this lands.
                        yield _sse(
                            "tool_call_complete",
                            {k: v for k, v in event.items() if k != "type"},
                        )
                    elif etype == "assistant":
                        msg = event.get("message", {}) or {}
                        yield _sse("assistant_message", {"message": msg})
                        to_persist.append(("assistant", _as_storable_content(msg.get("content"))))
                    elif etype == "user":
                        # Backend-executed tool_result rows — plain loop `user` events.
                        msg = event.get("message", {}) or {}
                        to_persist.append(("user", _as_storable_content(msg.get("content"))))
                    elif etype == "state_update":
                        state_payload = event.get("client_state")
                        state_dict = asdict(state_payload) if state_payload else {}
                        yield _sse("state_update", {"state": state_dict})
                    elif etype == "done":
                        usage = event.get("usage", usage)
                    elif etype == "compact_boundary":
                        # Mid-loop autoCompact (or reactive) fired. Emit the
                        # SSE event for the UI divider AND queue a system-role
                        # row so the next turn's history-load can apply the
                        # boundary filter and skip the pre-boundary slice.
                        # Without this persistence the model would re-see the
                        # full history next turn and autoCompact would re-fire,
                        # turning the LLM summary into a per-turn cost.
                        boundary_payload = event.get("boundary")
                        yield _sse(etype, {k: v for k, v in event.items() if k != "type"})
                        if boundary_payload is not None:
                            to_persist.append(("system", make_boundary_payload(boundary_payload)))
                    else:
                        yield _sse(etype, {k: v for k, v in event.items() if k != "type"})

            # Flush the 'completed' lifecycle event fired in query's finally.
            for frame in _drain_lifecycle():
                yield frame

            # ── 5. Persist every captured message. Retries on transient failure. ──
            for role, content in to_persist:
                if not content:
                    continue
                persisted = await _append_with_retry(
                    authorization, body.conversation_id, role=role, content=content
                )
                if persisted is None:
                    yield _sse(
                        "error",
                        {
                            "message": "Assistant response streamed but could not be persisted; "
                            "reload the conversation to see saved state.",
                        },
                    )
                    return

            # ── 6. Bump per-conversation totals + record usage entry. ──
            # Two writes, both best-effort, both informational:
            #
            #   * ``add_conversation_tokens`` bumps the running per-
            #     conversation counters (used by /context for accurate
            #     input footprint, and by the admin dashboard for
            #     project-level lifetime cost).
            #   * ``record_usage`` appends a row to ``usage_records`` so
            #     the user-facing /cost command and per-user admin
            #     dashboard see traffic broken down by model + day.
            #
            # Cost is computed once via ``calculate_cost(model, in, out)``
            # (the same formula already used elsewhere) and shared
            # between the two writes so they stay in lockstep.
            if usage and body.conversation_id:
                in_tok = int(usage.get("input_tokens") or 0)
                out_tok = int(usage.get("output_tokens") or 0)
                if in_tok or out_tok:
                    try:
                        cost_usd = float(calculate_cost(models.default_model, in_tok, out_tok))
                    except Exception:
                        # Unknown model + non-zero tokens raises; we never
                        # want cost lookup to break a turn so swallow.
                        log.warning(
                            "calculate_cost failed for model=%s",
                            models.default_model,
                            exc_info=True,
                        )
                        cost_usd = 0.0

                    await db_client.add_conversation_tokens(
                        authorization,
                        body.conversation_id,
                        input_tokens=in_tok,
                        output_tokens=out_tok,
                        cost_usd=cost_usd,
                    )

                    await db_client.record_usage(
                        user_id=user.user_id,
                        email=user.email,
                        display_name=user.display_name,
                        model=models.default_model,
                        input_tokens=in_tok,
                        output_tokens=out_tok,
                        cost_usd=cost_usd,
                    )
        finally:
            reset_command_lifecycle_listener(lifecycle_token)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        log.exception(f"agent_turn failed for user={user.user_id}: {exc}")
        yield _sse("error", {"message": str(exc)})
