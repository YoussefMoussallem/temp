"""
Agent FastAPI router.

POST /api/agent/turn  — runs one turn of the agentic loop, streams events
                        as Server-Sent Events back to chat-ui.

Stateless: each /turn request creates a fresh QueryEngine, hydrates the
opaque ClientState from the request body, runs the loop, ships state out
via the `state_update` SSE event. No server-side session tracking.

Phase 1.5: the basic /turn endpoint. /compact, /context, /usage, /skills
remain 501 stubs until their respective phases land.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass, is_dataclass
from typing import TYPE_CHECKING, Any, AsyncIterator, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.bridges import app_settings_client, db_client
from app.bridges.litellm_bridge import calculate_cost
from app.dependencies import CurrentUser, get_current_user
from app.middleware.rate_limit import limiter, user_or_ip_key
from app_logger import get_logger

from .QueryEngine import ClientState, QueryEngine
from .query.transitions import Terminal
from .services.compact.post_compact_cleanup import post_compact_cleanup
from .services.title_generator import generate_title
from .Tool import Tools, ToolUseContext
from .tools_registry import get_all_base_tools
from .types.permissions import PermissionAllowDecision
from .utils.command_lifecycle import (
    reset_command_lifecycle_listener,
    set_command_lifecycle_listener,
)
from .utils.compact_boundary_marker import (
    apply_boundary_filter,
    make_boundary_payload,
)
from .utils.process_user_input import process_user_input
from .utils.slash_command_parsing import is_slash_command

if TYPE_CHECKING:
    from pptx_master import LayoutDescriptor

log = get_logger(__name__)

router = APIRouter(prefix="/agent", tags=["agent"])


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
# Helpers
# ============================================================================


def _sse(event_type: str, data: Any) -> str:
    """Format a single SSE event."""
    return f"event: {event_type}\ndata: {json.dumps(data, default=_json_default)}\n\n"


def _json_default(obj: Any) -> Any:
    """JSON serializer for dataclasses + other non-serializable types."""
    if is_dataclass(obj):
        return asdict(obj)
    return str(obj)


async def _allow_all(_name: str, _input: dict) -> PermissionAllowDecision:
    """v1 permission gate — allows everything. Phase 4 wires real engine."""
    return PermissionAllowDecision(behavior="allow")


def _route_subagent_tool_results(
    messages: list[dict],
    pending_subagents: list[dict],
    consumed_ids: list[str],
) -> None:
    """Phase 6.B.1.7. Strip tool_result blocks belonging to paused
    subagents from the parent's user messages and re-route them into the
    matching frame's ``accumulatedMessages``.

    Why: Anthropic's API rejects tool_results whose tool_use_id isn't in
    the immediately preceding assistant message. Subagent tool_uses live
    in the subagent's OWN accumulatedMessages, not the parent's stream;
    leaving them in the parent's user message would poison the API call.

    Two ID populations get stripped here:
      1. **Active**: ids in ``pending_subagents[*].pendingToolUseIds`` —
         the immediate dispatch's results (route into the matching
         frame's accumulatedMessages).
      2. **Consumed**: ids in ``consumed_ids`` (ClientState's all-time
         subagent-owned tool_use_id ledger). Chat-ui's persisted history
         keeps subagent tool_results forever; without stripping prior
         turns' subagent IDs on every turn the parent's LLM call
         eventually sees stale tool_result blocks with no matching
         tool_use → 400. We don't re-route consumed ids (the matching
         frame may already be gone); we just drop them.

    In-place mutation of ``messages`` content arrays AND ``consumed_ids``
    (newly-routed ids get appended). Empty-after-extract user messages
    are removed entirely so we don't ship a content-less user message
    to the LLM.
    """
    id_to_frame: dict[str, dict] = {}
    for frame in pending_subagents or []:
        if not isinstance(frame, dict):
            continue
        for tu_id in frame.get("pendingToolUseIds") or []:
            if isinstance(tu_id, str) and tu_id:
                if tu_id in id_to_frame and id_to_frame[tu_id] is not frame:
                    log.warning(
                        "subagent_frame_id_collision",
                        extra={
                            "tu_id": tu_id,
                            "keeping_agentId": id_to_frame[tu_id].get("agentId"),
                            "rejected_agentId": frame.get("agentId"),
                        },
                    )
                    continue
                id_to_frame[tu_id] = frame

    consumed_set = set(consumed_ids or [])

    if not id_to_frame and not consumed_set:
        return

    indices_to_drop: list[int] = []
    for idx in range(len(messages) - 1, -1, -1):
        msg = messages[idx]
        if not isinstance(msg, dict) or msg.get("type") != "user":
            continue
        inner = msg.get("message")
        if not isinstance(inner, dict):
            continue
        content = inner.get("content")
        if not isinstance(content, list):
            continue

        keep_blocks: list[Any] = []
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                keep_blocks.append(block)
                continue
            tu_id = block.get("tool_use_id")
            if tu_id in id_to_frame:
                # Active route: append to frame's accumulatedMessages as a
                # standalone user message so the subagent's history reads:
                # ... assistant(tool_use) → user(tool_result).
                frame = id_to_frame[tu_id]
                acc = frame.setdefault("accumulatedMessages", [])
                acc.append({
                    "type": "user",
                    "message": {"role": "user", "content": [block]},
                })
                # Move from pendingToolUseIds → consumed_ids ledger so
                # future /turns strip without re-routing.
                pending = frame.get("pendingToolUseIds") or []
                frame["pendingToolUseIds"] = [p for p in pending if p != tu_id]
                if tu_id and tu_id not in consumed_set:
                    consumed_ids.append(tu_id)
                    consumed_set.add(tu_id)
                continue
            if tu_id in consumed_set:
                # Stale subagent result from a prior turn that chat-ui
                # re-sent. Already in some frame's accumulatedMessages
                # (or completed long ago). Drop without re-routing.
                continue
            keep_blocks.append(block)

        if not keep_blocks:
            indices_to_drop.append(idx)
        else:
            inner["content"] = keep_blocks

    for idx in indices_to_drop:
        messages.pop(idx)


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
    from .Tool import ToolUseContextOptions

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

        # Phase 6.B.1.7: route subagent tool_results into their pending
        # frames before the LLM sees the history.
        #   - Active dispatches: ids in pending_subagents[*].pendingToolUseIds
        #     (route into the matching frame's accumulatedMessages so
        #     AgentTool's resume path feeds them into the subagent loop).
        #   - Consumed-ledger ids: stale subagent tool_results that chat-ui
        #     persisted on prior turns and keeps re-sending. Drop without
        #     re-routing; the frame they belonged to may already be gone.
        # Both populations MUST be stripped from the parent's stream
        # before the LLM sees the history — Anthropic rejects tool_results
        # whose tool_use_id isn't in the immediately preceding assistant
        # message.
        _route_subagent_tool_results(
            messages,
            cs.pending_subagents,
            cs.consumed_subagent_tool_use_ids,
        )

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


# ============================================================================
# /export-deck — fire-and-forget deck → editable .pptx (button-driven)
# ============================================================================
#
# Same conversion pipeline as the ExportDeck agent tool, just without the
# agent loop: a frontend button clicks this endpoint directly so the user
# doesn't need to chat with the model to download a .pptx.
#
# Streams Server-Sent Events:
#   - event: progress, data: {message, current, total}
#   - event: deck_export_ready, data: {filename, slide_count, deck}
#   - event: error, data: {message}
#   - event: done, data: {}
#
# Frontend: see client/app/src/agent/exportDeckClient.js +
# components/deck/ExportDeckButton.jsx.


class ExportDeckRequest(BaseModel):
    project_id: str
    filename: str | None = None


@router.post("/export-deck")
# Export is heavy (per-slide LLM HTML→pptxgenjs conversion). 20/min/user
# is plenty for normal "export this deck" clicks (most users export
# once or twice in a session) but stops a script driving the export
# endpoint in a tight loop and burning LLM budget.
@limiter.limit("20/minute", key_func=user_or_ip_key)
async def export_deck(
    request: Request,
    body: ExportDeckRequest,
    authorization: str | None = Header(default=None),
    _user: CurrentUser = Depends(get_current_user),
):
    """Run the same per-slide HTML→pptxgenjs conversion as the agent
    tool, but driven by a UI button instead of an LLM tool call.

    The ``_user`` parameter exists so FastAPI runs ``get_current_user``
    (which validates the JWT) — the value itself isn't needed here
    because authorization is forwarded raw to db-service.

    Streams progress + final deck spec as SSE; the browser assembles
    the .pptx from the spec via pptxgenjs."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    return StreamingResponse(
        _stream_export_deck(body, authorization),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


async def _stream_export_deck(
    body: ExportDeckRequest,
    authorization: str,
) -> AsyncIterator[str]:
    """SSE generator: forwards `build_deck_spec`'s on_progress events to
    the wire and emits `deck_export_ready` at the end."""
    from .tools.ExportDeckTool.ExportDeckTool import build_deck_spec  # noqa: PLC0415

    progress_q: asyncio.Queue[dict] = asyncio.Queue()
    done_sentinel = object()

    def on_progress(p: dict) -> None:
        # build_deck_spec is async, but on_progress is called from inside
        # the event loop, so put_nowait is safe.
        progress_q.put_nowait(p)

    # Admin-managed export model. Falls back to the resolved default
    # model when no export-specific override is set (see
    # ``app_settings_client.resolve``).
    models = await app_settings_client.resolve(authorization)
    convert_model = models.export_model

    async def runner():
        try:
            return await build_deck_spec(
                authorization=authorization,
                project_id=body.project_id,
                filename=body.filename,
                model=convert_model,
                on_progress=on_progress,
            )
        finally:
            progress_q.put_nowait(done_sentinel)  # type: ignore[arg-type]

    task = asyncio.create_task(runner())

    # Drain progress events as they come in. We can't `await task` and
    # `await progress_q.get()` simultaneously without juggling — so we
    # signal completion via the sentinel.
    while True:
        item = await progress_q.get()
        if item is done_sentinel:
            break
        yield _sse("progress", item)

    try:
        deck_spec, total, filename = await task
    except Exception as exc:  # noqa: BLE001
        log.exception("export-deck failed for project=%s: %s", body.project_id, exc)
        yield _sse("error", {"message": str(exc)})
        return

    if total == 0:
        yield _sse("error", {"message": "No slides to export."})
        return

    yield _sse(
        "deck_export_ready",
        {
            "filename": filename,
            "slide_count": total,
            "deck": deck_spec,
        },
    )
    yield _sse("done", {})


# ============================================================================
# Conversation auto-title
# ============================================================================
#
# Best-effort title generation triggered by the FE right after creating a
# fresh conversation. The actual prompt + sanitisation lives in
# ``services.title_generator``; this endpoint is just the HTTP surface
# that wires user authorization, the search-model resolution, and the
# subsequent PATCH to db-service into one call.


class GenerateTitleRequest(BaseModel):
    """Body of POST /agent/conversations/{id}/generate-title.

    ``prompt`` is the user's first message in the conversation. We send
    only the text body — images are ignored for titling.
    """

    prompt: str


class GenerateTitleResponse(BaseModel):
    """Response shape. ``title`` is None when generation failed (any
    reason — LLM error, sanitisation produced empty string, etc.). The
    FE should leave its placeholder ("New chat") in place in that case
    rather than blanking the sidebar entry.
    """

    title: str | None = None


@router.post("/conversations/{conversation_id}/generate-title")
async def generate_conversation_title(
    conversation_id: str,
    body: GenerateTitleRequest,
    authorization: str | None = Header(default=None),
    user: CurrentUser = Depends(get_current_user),  # noqa: ARG001 — auth check via dependency
) -> GenerateTitleResponse:
    """Generate a 4-6 word title from the user's first prompt and PATCH
    the conversation row on db-service.

    Best-effort: every failure path (LLM error, empty title, db-service
    PATCH failure) returns ``{title: None}`` and logs at WARNING. The FE
    falls back to its placeholder in that case. We intentionally don't
    surface a 500 here — title generation is a UX nicety, not a
    correctness requirement.
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization")

    # Resolve the title model — admin-configurable; falls back to the
    # main ``default_model`` if no title-specific override is set. Title
    # generation is short and latency-sensitive, so admins typically
    # point this at a small/fast model (e.g. a 7-8B class) even when
    # the main loop runs a larger one.
    models = await app_settings_client.resolve(authorization)

    title = await generate_title(body.prompt, model=models.title_model)
    if not title:
        return GenerateTitleResponse(title=None)

    try:
        await db_client.update_conversation_title(
            authorization,
            conversation_id,
            title=title,
        )
    except Exception:  # noqa: BLE001
        log.warning(
            "Title PATCH to db-service failed for conversation %s",
            conversation_id,
            exc_info=True,
        )
        # The LLM produced a title but persistence failed. Return None so
        # the FE doesn't optimistically render a value the DB doesn't
        # know about. The FE keeps its placeholder; the next manual
        # rename or a retry will sync.
        return GenerateTitleResponse(title=None)

    return GenerateTitleResponse(title=title)


# ============================================================================
# Stub endpoints (filled in later phases)
# ============================================================================


def _not_implemented():
    raise HTTPException(
        status_code=501,
        detail="Endpoint not yet implemented in current phase.",
    )


@router.post("/compact")
async def compact():
    """Compact endpoint — Phase 3."""
    _not_implemented()


@router.post("/context")
async def context():
    """Context stats endpoint — Phase 3."""
    _not_implemented()


@router.get("/usage")
async def usage():
    """Per-session usage display — Phase 5."""
    _not_implemented()


@router.get("/skills")
async def list_skills():
    """List all available skills.

    Skills are PromptCommands (Phase 2.7b.1) loaded from
    ``skills/bundled``, ``~/.edwin/skills``, and ``<cwd>/.edwin/skills``.
    The /commands endpoint already returns these too — this endpoint is a
    skills-only filter for the legacy ``/skills`` slash command's UI.
    """
    from .skills.discovery import discover_skills

    return [
        {
            "name": s.get("name", ""),
            "description": s.get("description", ""),
            "aliases": list(s.get("aliases") or []),
            "when_to_use": s.get("when_to_use", ""),
        }
        for s in await discover_skills()
        if not s.get("is_hidden")
    ]


@router.get("/models")
def list_models():
    """Return all available models from the LiteLLM proxy."""
    from app.bridges.litellm_bridge import get_all_model_info

    return [{"id": m["name"], **m} for m in get_all_model_info()]


@router.get("/commands")
async def list_commands():
    """Canonical command registry. Frontend uses this for typeahead + dispatch.

    For each command:
      - name, description, aliases, argument_hint: presentation metadata
      - type: "prompt" | "local"
      - execution: "server" — backend runs it (prompt or local); frontend
        sends via /turn and waits for expansion / lifecycle.
      - execution: "client" — frontend runs it; backend only holds metadata
        so discovery is unified. Frontend looks up a local handler by name.
    """
    from .commands import get_command_name, load_all_commands

    out = []
    for c in await load_all_commands():
        out.append(
            {
                "name": get_command_name(c),
                "description": c.get("description", ""),
                "aliases": list(c.get("aliases") or []),
                "argument_hint": c.get("argument_hint", ""),
                "type": c.get("type", "local"),
                # Prompt commands always execute server-side. Local commands
                # carry an explicit execution tag (defaults to server if missing).
                "execution": c.get("execution", "server"),
                "is_hidden": bool(c.get("is_hidden", False)),
            }
        )
    return out


# ============================================================================
# /memories/from-text — UI-driven memory create/edit (Phase 3.5)
# ============================================================================
# End users write memories in plain English; the backend calls an LLM to
# structure the input into the persisted schema (slug / type / name /
# description / body), then upserts via db-service. The agent's tool-
# gated read/save pattern is unchanged — this is a sibling channel
# powered by the UI drawer.


class MemoryFromTextRequest(BaseModel):
    scope: Literal["user", "project"]
    text: str
    # Required when scope == "project". Ignored for scope == "user"
    # (the caller's own oid is used instead).
    project_id: str | None = None
    # When present, forces the structured output to use THIS slug —
    # signalling "I'm editing this specific entry". Without it the
    # LLM picks a slug (potentially reusing an existing one if the
    # text supersedes; potentially creating a fresh one if not).
    slug: str | None = None


@router.post("/memories/from-text")
# Each save is one LLM call. 30/min is generous for interactive use
# (a user typing memories) but stops a script that spams the endpoint
# from burning model budget. Same key as /turn so a user's overall
# memory + chat budget stays comparable.
@limiter.limit("30/minute", key_func=user_or_ip_key)
async def memory_from_text(
    request: Request,
    body: MemoryFromTextRequest,
    authorization: str | None = Header(default=None),
    user: CurrentUser = Depends(get_current_user),
):
    """Structure plain text into a memory and upsert it.

    Returns the saved memory (same shape as the GET endpoints), so the
    FE can render it in the list without a separate refetch.
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    if not body.text or not body.text.strip():
        raise HTTPException(status_code=400, detail="text is required")
    if body.scope == "project" and not body.project_id:
        raise HTTPException(
            status_code=400,
            detail="project_id is required for scope=project",
        )

    # Late import — pulls in the LLM provider stack which is heavy at
    # module load time.
    from .services.memories import structure_memory_text  # noqa: PLC0415

    # Fetch the existing index so the LLM can detect supersession /
    # contradiction and reuse a slug rather than create a sibling.
    if body.scope == "user":
        existing = await db_client.list_user_memories(authorization, user.user_id)
    else:
        existing = await db_client.list_project_memories(
            authorization,
            body.project_id or "",
        )

    try:
        structured = await structure_memory_text(
            authorization=authorization,
            text=body.text,
            scope=body.scope,
            existing_index=existing,
            force_slug=body.slug,
        )
    except ValueError as e:
        # Bad LLM output (non-JSON, missing field, malformed). Surface
        # as 422 so the FE can show a friendly retry prompt.
        raise HTTPException(status_code=422, detail=str(e)) from e

    try:
        if body.scope == "user":
            saved = await db_client.upsert_user_memory(
                authorization,
                user.user_id,
                **structured,
            )
        else:
            saved = await db_client.upsert_project_memory(
                authorization,
                body.project_id or "",
                **structured,
            )
    except Exception as e:  # noqa: BLE001
        log.exception("memory_from_text: upsert failed: %s", e)
        raise HTTPException(status_code=502, detail="Failed to persist memory") from e

    return saved


# ============================================================================
# Master upload — frontend file picker for the Master Manager
# ============================================================================
#
# Multipart entry point so a 5–100 MB .pptx doesn't have to round-trip
# through the LLM as base64 in a tool call. Flow:
#
#   FE picker → multipart POST here → extract manifest from bytes →
#   forward {manifest, sha, b64} to db-service → db-service uploads
#   bytes to blob and writes the row
#
# We extract on the backend (not db-service) because slide_ir lives
# here — the extractor depends on python-pptx + lxml which are heavy
# imports we'd rather not pay for in db-service.

# Bytes go to Azure Blob, not Postgres BYTEA, so the practical ceiling
# is the LLM's appetite for re-extracting the manifest each turn (it's
# cheap — JSON is small). 100 MB covers heavily-illustrated corporate
# templates. Sized to match the ImportMasterTool guard.
_MAX_MASTER_UPLOAD_BYTES = 100 * 1024 * 1024


# Phase C — bundled brand fonts. The user uploads .ttf/.otf alongside
# the .pptx; we infer family/weight/style from the filename so the FE
# never has to ask. db-service caps per-file (5 MB) and total (25 MB)
# size; matching the per-file cap here prevents wasting a multipart
# parse on a font we'd reject downstream.
_MAX_FONT_BYTES = 5 * 1024 * 1024
_FONT_EXTENSIONS = {"ttf", "otf", "woff", "woff2"}

# Lower-case stem suffix → CSS weight number. Order matters when a
# longer name contains a shorter one (``ExtraBold`` would otherwise
# match ``Bold``); we look up by the longest hit, see _infer_font_meta.
_WEIGHT_TOKENS: dict[str, int] = {
    "thin": 100,
    "hairline": 100,
    "ultralight": 200,
    "extralight": 200,
    "light": 300,
    "book": 400,
    "regular": 400,
    "normal": 400,
    "medium": 500,
    "semibold": 600,
    "demibold": 600,
    "bold": 700,
    "extrabold": 800,
    "ultrabold": 800,
    "heavy": 900,
    "black": 900,
}


def _infer_font_meta(filename: str) -> dict:
    """Heuristically pull ``family``, ``weight``, ``style`` from a font
    filename like ``STCForward-Bold.ttf`` or ``Fund-LightItalic.ttf``.

    Algorithm:
    1. Strip extension.
    2. Lower-case-search for the longest weight-token match; remove it.
    3. Lower-case-search for ``italic`` / ``oblique``; remove it.
    4. Split on ``-`` / ``_`` and reassemble with spaces — that's the
       family. Empty fallbacks → original stem.

    Heuristics are best-effort. If a vendor uses a different naming
    convention the worst case is weight 400 / style normal — the
    consumption side will still find the file by family + filename.
    """
    stem = filename.rsplit(".", 1)[0]
    lower = stem.lower()

    weight = 400
    matched_token: str | None = None
    for token in sorted(_WEIGHT_TOKENS, key=len, reverse=True):
        if token in lower:
            weight = _WEIGHT_TOKENS[token]
            matched_token = token
            break

    style = "normal"
    if "italic" in lower or "oblique" in lower:
        style = "italic"

    cleaned = lower
    if matched_token:
        cleaned = cleaned.replace(matched_token, "")
    cleaned = cleaned.replace("italic", "").replace("oblique", "")
    # Split on common delimiters and drop empties.
    pieces = [p.strip() for sep in ("-", "_") for p in cleaned.replace(" ", sep).split(sep)]
    family_raw = " ".join(p for p in pieces if p) or stem
    # Title-case the family — "stcforward" → "Stcforward" reads worse
    # than the original mixed case, so we re-derive from the original
    # stem when our cleaned slug looks fine.
    family = family_raw.strip().title()
    return {"family": family, "weight": weight, "style": style}


async def _build_fonts_payload(font_uploads: list) -> list[dict]:
    """Read each multipart font file, validate, base64-encode, and
    return the list ready for ``db_client.create_master(fonts=...)``.

    Validation rejects empty files, oversized files, and disallowed
    extensions early (saving a round-trip to db-service). Filename
    metadata is inferred via ``_infer_font_meta`` so the FE only has
    to upload the file.
    """
    import base64 as _b64  # noqa: PLC0415

    payload: list[dict] = []
    for f in font_uploads:
        if not hasattr(f, "read"):
            continue
        font_filename = getattr(f, "filename", "") or ""
        if not font_filename:
            raise HTTPException(
                status_code=400,
                detail="font upload missing filename",
            )
        ext = font_filename.rsplit(".", 1)[-1].lower() if "." in font_filename else ""
        if ext not in _FONT_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"font {font_filename!r}: extension must be one of {sorted(_FONT_EXTENSIONS)}"
                ),
            )
        if "/" in font_filename or "\\" in font_filename:
            raise HTTPException(
                status_code=400,
                detail=f"font {font_filename!r}: filename must not contain path separators",
            )

        font_bytes = await f.read()
        if not font_bytes:
            raise HTTPException(
                status_code=400,
                detail=f"font {font_filename!r}: empty file",
            )
        if len(font_bytes) > _MAX_FONT_BYTES:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"font {font_filename!r}: {len(font_bytes)} bytes exceeds "
                    f"{_MAX_FONT_BYTES}-byte cap"
                ),
            )

        meta = _infer_font_meta(font_filename)
        payload.append(
            {
                "filename": font_filename,
                "family": meta["family"],
                "weight": meta["weight"],
                "style": meta["style"],
                "bytes_b64": _b64.b64encode(font_bytes).decode("ascii"),
                "source": "uploaded",
            }
        )

    return payload


@router.post("/masters/upload")
@limiter.limit("10/minute", key_func=user_or_ip_key)
async def masters_upload(
    request: Request,
    authorization: str | None = Header(default=None),
    user: CurrentUser = Depends(get_current_user),
):
    """Upload a .pptx as a project master.

    Multipart form fields:
      * ``file`` — the .pptx (or .potx) bytes
      * ``project_id`` — UUID of the parent project
      * ``name`` (optional) — display label; falls back to the PPTX
        core-properties title or 'Imported master'

    Returns ``{"master": <row>, "summary": <manifest summary>}`` so
    the FE can drop the row into local state without a refetch.
    Idempotent on (project_id, source_sha256): re-uploading the same
    .pptx into the same project refreshes the existing row.
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    form = await request.form()
    upload = form.get("file")
    project_id = (form.get("project_id") or "").strip()
    name = (form.get("name") or "").strip() or None
    # Phase C: optional bundled brand fonts. Each font posted as a
    # repeated form field named ``fonts``. We infer family/weight/style
    # from the filename below — the FE never has to compute it.
    font_uploads = form.getlist("fonts")

    if not project_id:
        raise HTTPException(status_code=400, detail="project_id is required")
    if upload is None or not hasattr(upload, "read"):
        raise HTTPException(status_code=400, detail="file is required")

    # Keep the original casing for fallback naming below; only lowercase
    # the suffix-check copy.
    filename_raw = getattr(upload, "filename", "") or ""
    filename = filename_raw.lower()
    if not (filename.endswith(".pptx") or filename.endswith(".potx")):
        raise HTTPException(status_code=400, detail="Expected a .pptx or .potx upload")

    data = await upload.read()
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    if len(data) > _MAX_MASTER_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(f"File too large ({len(data)} bytes); limit is {_MAX_MASTER_UPLOAD_BYTES}."),
        )

    # Deferred imports keep the route cheap on cold start when no
    # one has uploaded yet — extracting pulls python-pptx + lxml
    # (~30MB working memory).
    import base64  # noqa: PLC0415

    from pptx_master import extract_master_from_pptx  # noqa: PLC0415
    from app.services.pptx_renderer import PptxRenderer  # noqa: PLC0415

    try:
        manifest = extract_master_from_pptx(data, name=name)
    except Exception as e:  # noqa: BLE001
        log.exception("masters_upload: failed to parse PPTX")
        raise HTTPException(status_code=422, detail=f"Failed to parse PPTX: {e}") from e

    # Fall back to the upload's filename when extraction yielded the
    # generic default. Two masters that were both extracted to
    # ``"Imported master"`` are indistinguishable in the curation list,
    # which has bitten users (wrong-master activations). The filename
    # is the most discriminating bit of metadata available without
    # hitting the .pptx core props (which were already empty if we got
    # here).
    # PowerPoint's default core-property titles aren't useful as master
    # names — every blank-deck-saved-as-template ships with one of these
    # literal strings. Treat them as "no real title" and prefer the
    # upload's filename so users can tell their masters apart.
    _DEFAULT_PPTX_TITLES = {
        "Imported master",
        "PowerPoint Presentation",
        "Untitled",
        "Presentation1",
        "Slide Show",
        "Slide1",
    }
    if manifest.name in _DEFAULT_PPTX_TITLES and filename_raw:
        from pathlib import Path  # noqa: PLC0415

        manifest.name = Path(filename_raw).stem or manifest.name

    # Build the flat list of (master_index, layout_index) pairs for both
    # the renderer and the db-service payload. Walk masters[] when present
    # (Phase 2.1+); fall back to the legacy single-master ``layouts`` for
    # back-compat with any synthetic fixture that still uses it.
    if manifest.masters:
        flat_layouts: list[tuple[int, int, LayoutDescriptor]] = [
            (m.index, idx, lay) for m in manifest.masters for idx, lay in enumerate(m.layouts)
        ]
        master_palettes: dict[int, dict] = {m.index: dict(m.palette) for m in manifest.masters}
        master_fonts: dict[int, dict] = {m.index: dict(m.fonts) for m in manifest.masters}
        master_theme_idx: dict[int, int] = {m.index: m.theme_index for m in manifest.masters}
    else:
        flat_layouts = [(lay.master_index, idx, lay) for idx, lay in enumerate(manifest.layouts)]
        master_palettes = {0: dict(manifest.theme.colors)}
        master_fonts = {0: dict(manifest.theme.fonts)}
        master_theme_idx = {0: 1}

    # Best-effort: render previews via the sidecar. Failures (sidecar
    # unreachable, timeout, etc.) demote to "no previews" — the master
    # is still importable, the FE just shows placeholder cards.
    specs = [(m_idx, lay.layout_index) for m_idx, _pos, lay in flat_layouts]
    previews: dict[tuple[int, int], bytes] = {}
    try:
        previews = await PptxRenderer().render_layouts(data, specs)
        log.info(
            "masters_upload: rendered %d / %d layout previews",
            len(previews),
            len(specs),
        )
    except Exception:  # noqa: BLE001
        log.warning("masters_upload: layout preview rendering failed", exc_info=True)
        previews = {}

    layouts_payload: list[dict] = []
    for m_idx, position, lay in flat_layouts:
        png = previews.get((m_idx, lay.layout_index))
        layouts_payload.append(
            {
                "master_index": m_idx,
                "layout_index": lay.layout_index,
                "name": lay.name,
                "auto_kind": lay.kind,
                "position": position,
                "placeholders": [p.model_dump() for p in lay.placeholders],
                "safe_area": lay.safe_area.model_dump() if lay.safe_area else None,
                "theme_index": master_theme_idx.get(m_idx, 1),
                "font_major": master_fonts.get(m_idx, {}).get("major"),
                "font_minor": master_fonts.get(m_idx, {}).get("minor"),
                "palette": master_palettes.get(m_idx, {}),
                "preview_b64": (base64.b64encode(png).decode("ascii") if png else None),
            }
        )

    fonts_payload = await _build_fonts_payload(font_uploads)

    try:
        master = await db_client.create_master(
            authorization,
            project_id,
            name=manifest.name,
            manifest=manifest.model_dump(),
            source_sha256=manifest.source_sha256,
            source_pptx_b64=base64.b64encode(data).decode("ascii"),
            layouts=layouts_payload,
            fonts=fonts_payload or None,
        )
    except Exception as e:  # noqa: BLE001
        log.exception("masters_upload: db-service create_master failed")
        raise HTTPException(status_code=502, detail="Failed to persist master") from e

    return {
        "master": master,
        "summary": {
            "name": manifest.name,
            "canvas": manifest.canvas.model_dump(),
            "fonts": manifest.theme.fonts,
            "primary_color": manifest.theme.colors.get("primary"),
            "safe_area": manifest.safe_area.model_dump(),
            "chrome_elements": len(manifest.chrome),
            "layouts": [{"name": layout.name, "kind": layout.kind} for layout in manifest.layouts],
        },
    }
