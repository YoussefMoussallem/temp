"""POST /agent/turn — the FastAPI route + SSE streaming generator.

Stateless: each /turn request creates a fresh QueryEngine, hydrates the
opaque ClientState from the request body, runs the loop, ships state out
via the ``state_update`` SSE event. No server-side session tracking.

The ``router`` symbol used by ``@router.post`` is defined in
``__init__.py``; this module imports it and registers via decorator
side-effect when the package is loaded.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import AsyncIterator

from fastapi import Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.bridges import app_settings_client, db_client
from app.bridges.litellm_bridge import calculate_cost
from app.dependencies import CurrentUser, get_current_user
from app.middleware.rate_limit import limiter, user_or_ip_key
from app_logger import get_logger

from ...QueryEngine import ClientState, QueryEngine
from ...query.transitions import Terminal
from ...Tool import Tools
from ...tools_registry import get_all_base_tools
from ...utils.command_lifecycle import (
    reset_command_lifecycle_listener,
    set_command_lifecycle_listener,
)
from ...utils.compact_boundary_marker import make_boundary_payload
from .._shared import _sse
from . import router
from .helpers import _allow_all, _append_with_retry, _as_storable_content
from .messages import (
    _build_turn_messages,
    _MessagesError,
    _MessagesShortCircuit,
)
from .schemas import AgentTurnRequest

log = get_logger(__name__)


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
