"""
The agentic loop.

Port of src/query.ts (1732 lines in source).

NAMING NOTE — parity compromise:
Source TS has BOTH `src/query.ts` (root file, the loop) AND `src/query/`
(subdir with deps.ts, transitions.ts). Python literally cannot have both
`query.py` and `query/` in the same package — `PathFinder` always picks
the package and shadows the module. To preserve `query/` with its own
files (so `from agent.query.deps import X` works as in source), the loop
file is renamed `query_loop.py` here. Callers should import via:
  from agent.query_loop import State, QueryParams, query
  from agent.query.deps import QueryDeps
  from agent.query.transitions import Terminal, Continue

v1 implements the MINIMAL functional loop:
  1. Yield stream_request_start
  2. Call model (streaming)
  3. Collect assistant message + tool_use blocks
  4. If no tool_use → return Terminal(completed)
  5. Execute tool_use blocks (serial in v1)
  6. Append tool results to messages
  7. Continue loop (next iteration)

DEFERRED for later phases:
  - Context preprocessing pipeline (microcompact, snipCompact, autoCompact,
    contextCollapse) → Phase 3
  - Recovery escalation (max_output_tokens, prompt_too_long) → Phase 3
  - Streaming/parallel tool execution → Phase 2/3
  - Stop hooks (preventContinuation) → Phase 4
  - Token budget tracking → Phase 3
  - Memory prefetch / skill prefetch → Phase 5
  - Job classifier → Phase 1.deferred (see Q10 jobs/)

Per stateless backend principle: query() takes State as input, ships State
out via the generator's return value (Terminal). NO singleton; NO persistence
between calls. QueryEngine.py wraps query() per /turn request.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, AsyncGenerator

from app_logger import get_logger

from .Tool import ToolUseContext, find_tool_by_name, Tools
from .query.deps import QueryDeps, production_deps
from .query.transitions import Continue, Terminal
from .services.api.with_retry import MaxRetriesExceeded, with_retry
from .services.compact.compact_warning_hook import compact_warning_hook
from .services.compact.reactive_compact import reactive_compact
from .services.compact.snip_compact import snip_compact_if_needed
from .types.hooks import CanUseToolFn
from .utils.command_lifecycle import notify_command_lifecycle
from .utils.context_collapse import apply_collapses_if_needed

log = get_logger(__name__)

# Sentinel used by the parallel-chunk funnel to signal that a runner task
# has finished producing events. Identity comparison only.
_RUNNER_DONE = object()
# Sentinel that `_run_call` puts on its progress queue in `finally`, so the
# `_execute_single_tool` drain loop exits even when the tool raised.
_CALL_DONE = object()

if TYPE_CHECKING:
    from .types.message import (
        AssistantMessage,
        Message,
        UserMessage,
    )


# ============================================================================
# QueryParams
# ============================================================================


@dataclass
class QueryParams:
    """
    Input to query(). Passed in by QueryEngine per /turn request.

    Subset of source's QueryParams. Deferred fields:
      - systemPrompt (Phase 1.3 — uses context.py)
      - userContext / systemContext (Phase 1.3)
      - taskBudget (Phase 3)
      - skipCacheWrite (Phase 3 prompt cache)
      - maxOutputTokensOverride (Phase 3 recovery)
    """

    messages: list["Message"]
    tools: Tools
    canUseTool: CanUseToolFn
    toolUseContext: ToolUseContext
    systemPrompt: str = ""
    fallbackModel: str | None = None
    querySource: str = "agent"
    maxTurns: int | None = None
    deps: QueryDeps | None = None
    # Slash-command uuids consumed by this turn. The loop fires "started" on
    # each at entry, then "completed" on normal turn end (see query()).
    # Source: query.ts:229 consumedCommandUuids.
    command_uuids: list[str] = field(default_factory=list)


# ============================================================================
# State (mutable across iterations)
# ============================================================================


@dataclass
class State:
    """
    Mutable state carried between loop iterations.

    Mirrors src/query.ts:204. Most fields are deferred-feature placeholders
    that v1 reads-but-doesn't-write. Continue sites write `state =
    replace(state, ...)` instead of N separate assignments.
    """

    messages: list["Message"]
    toolUseContext: ToolUseContext
    turnCount: int = 1
    # Phase 3 compaction tracking (3.1 scaffolding).
    # ``consecutive_autocompact_failures`` is bumped by the autocompact stage
    # on exception, reset on success. Threaded across iterations so a stage
    # that fails N times in a row can be downgraded by ``with_retry`` (3.5).
    consecutive_autocompact_failures: int = 0
    autoCompactTracking: Any = None  # Phase 3 (free-form metadata bag)
    maxOutputTokensRecoveryCount: int = 0  # Phase 3 recovery
    hasAttemptedReactiveCompact: bool = False  # Phase 3 recovery
    maxOutputTokensOverride: int | None = None  # Phase 3 recovery
    pendingToolUseSummary: Any = None  # Phase 3 microcompact
    stopHookActive: bool | None = None  # Phase 4 stop hooks
    transition: Continue | None = None  # records why prev iteration continued


# ============================================================================
# Helpers
# ============================================================================


def _extract_tool_uses(assistant_msg: "AssistantMessage") -> list[dict[str, Any]]:
    """Pull tool_use content blocks out of an assistant message."""
    inner = assistant_msg.get("message") if isinstance(assistant_msg, dict) else None
    if not inner:
        return []
    content = inner.get("content")
    if not isinstance(content, list):
        return []
    return [
        block for block in content if isinstance(block, dict) and block.get("type") == "tool_use"
    ]


def _make_tool_result_message(
    tool_use_id: str,
    output: Any,
    is_error: bool = False,
) -> "UserMessage":
    """
    Wrap a tool result into a UserMessage with a tool_result content block.
    Mirrors createUserMessage with tool_result content from src/utils/messages.ts.
    """
    return {
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": str(output) if output is not None else "",
                    "is_error": is_error,
                }
            ],
        },
    }  # type: ignore[return-value]


def _is_interactive(tool: Any) -> bool:
    return bool(
        tool is not None
        and hasattr(tool, "requires_user_interaction")
        and tool.requires_user_interaction()
    )


def _is_safe(tool: Any, tool_input: Any) -> bool:
    return bool(
        tool is not None
        and hasattr(tool, "is_concurrency_safe")
        and tool.is_concurrency_safe(tool_input)
    )


async def _execute_single_tool(
    tool_use_block: dict[str, Any],
    tools: Tools,
    ctx: ToolUseContext,
    can_use_tool: CanUseToolFn,
    parent_message: Any,
) -> AsyncGenerator[Any, None]:
    """Yield every stream event for one tool_use: tool_progress events while
    the tool runs, any tool-emitted events (slide_created, etc.), then the
    tool_result UserMessage. Errors are mapped to an is_error tool_result
    so a single failing tool can't abort the whole chunk.

    Progress streams via an `asyncio.Queue`: `tool.call` is kicked off as a
    task with an `on_progress` callback that enqueues `tool_progress` SSE
    events. The generator drains the queue (yielding progress live) until a
    sentinel is put in the task's finally block, then awaits the task for
    its result (or the exception it raised).
    """
    tool_use_id = tool_use_block.get("id", "")
    tool_name = tool_use_block.get("name", "")
    tool_input = tool_use_block.get("input", {})

    # ``tool_call_complete`` is yielded EXACTLY once per call (in the
    # outer ``finally``), carrying the actual completion outcome. This
    # is the wire-level signal the FE uses to seal the tool's spinner:
    # ``tool_call_done`` from the model SDK only means "model finished
    # emitting the tool_use block," not "tool finished executing."
    # The execution window between those two is what tools like
    # WebSearch spend doing real work — that's where the spinner needs
    # to keep spinning.
    is_error_outcome = False
    try:
        tool = find_tool_by_name(tools, tool_name)
        if tool is None:
            is_error_outcome = True
            yield _make_tool_result_message(
                tool_use_id, f"Unknown tool: {tool_name}", is_error=True
            )
            return

        try:
            if ctx.options.permissionMode == "plan" and not tool.is_read_only():
                is_error_outcome = True
                yield _make_tool_result_message(
                    tool_use_id,
                    "You're in plan mode. Call ExitPlanMode to submit your plan for approval before making changes.",
                    is_error=True,
                )
                return

            validation = await tool.validate_input(tool_input, ctx)
            if not validation.result:
                is_error_outcome = True
                yield _make_tool_result_message(
                    tool_use_id,
                    getattr(validation, "message", "Validation failed"),
                    is_error=True,
                )
                return

            progress_q: asyncio.Queue = asyncio.Queue()

            def on_progress(data: Any) -> None:
                # Tools call this synchronously from inside `call`. Unbounded
                # put so we never block the tool on a slow consumer; if a tool
                # ever floods progress we'd add a maxsize + drop policy here.
                progress_q.put_nowait(
                    {"type": "tool_progress", "tool_use_id": tool_use_id, "data": data}
                )

            async def _run_call() -> Any:
                try:
                    return await tool.call(
                        tool_input,
                        ctx,
                        can_use_tool,
                        parent_message=parent_message,
                        on_progress=on_progress,
                    )
                finally:
                    # Unblock the drain loop whether the call returned or raised.
                    progress_q.put_nowait(_CALL_DONE)

            task = asyncio.create_task(_run_call())
            while True:
                ev = await progress_q.get()
                if ev is _CALL_DONE:
                    break
                yield ev

            result = await task  # re-raises if tool.call raised

            if result.events:
                for ev in result.events:
                    yield ev

            block = tool.map_tool_result_to_block(result.data, tool_use_id)
            yield {
                "type": "user",
                "message": {"role": "user", "content": [block]},
            }
        except Exception as e:  # noqa: BLE001
            is_error_outcome = True
            log.warning("tool %s (%s) raised: %s", tool_name, tool_use_id, e, exc_info=True)
            yield _make_tool_result_message(
                tool_use_id, f"Tool execution failed: {e}", is_error=True
            )
    finally:
        yield {
            "type": "tool_call_complete",
            "call_id": tool_use_id,
            "name": tool_name,
            "success": not is_error_outcome,
        }


async def _run_parallel_chunk(
    chunk: list[dict[str, Any]],
    tools: Tools,
    ctx: ToolUseContext,
    can_use_tool: CanUseToolFn,
    parent_message: Any,
) -> AsyncGenerator[tuple[int, Any], None]:
    """Run a chunk of concurrency-safe tools in parallel. Yields (idx, event)
    tuples as each tool emits, where idx is the tool's position in `chunk`.
    Events may interleave across tools; the caller uses idx to preserve
    original order for the tool_results list fed back to the model.
    """
    queue: asyncio.Queue = asyncio.Queue()

    async def runner(idx: int, tool_use_block: dict[str, Any]) -> None:
        try:
            async for ev in _execute_single_tool(
                tool_use_block, tools, ctx, can_use_tool, parent_message
            ):
                await queue.put((idx, ev))
        finally:
            await queue.put((idx, _RUNNER_DONE))

    tasks = [asyncio.create_task(runner(i, tu)) for i, tu in enumerate(chunk)]
    done_count = 0
    try:
        while done_count < len(chunk):
            idx, ev = await queue.get()
            if ev is _RUNNER_DONE:
                done_count += 1
                continue
            yield idx, ev
    finally:
        for t in tasks:
            if not t.done():
                t.cancel()


# ============================================================================
# query() — the agentic loop
# ============================================================================


async def query(
    params: QueryParams,
) -> AsyncGenerator[Any, None]:
    """
    The agentic loop — minimal v1.

    Yields stream events + messages as they happen. Returns Terminal at end
    (Python AsyncGenerator return values are accessed via StopAsyncIteration's
    .value, but for usability we yield the Terminal as the final event too).

    Phase 1.2 = MINIMAL impl; Phase 3 adds full preprocessing + recovery.
    """
    # Turn-local list of slash-command uuids consumed this turn. Fire
    # "started" on entry, "completed" in finally — matches source query.ts:229.
    consumed_command_uuids: list[str] = list(params.command_uuids or [])
    for _uuid in consumed_command_uuids:
        notify_command_lifecycle(_uuid, "started")
    try:
        async for _ev in _query_body(params):
            yield _ev
    finally:
        for _uuid in consumed_command_uuids:
            notify_command_lifecycle(_uuid, "completed")


async def _query_body(
    params: QueryParams,
) -> AsyncGenerator[Any, None]:
    """Inner loop. Kept separate so query() can wrap it in the consumed-command
    lifecycle try/finally without re-indenting the whole body."""
    deps = params.deps or production_deps()

    state = State(
        messages=list(params.messages),
        toolUseContext=params.toolUseContext,
    )

    while True:
        # Iteration entry — destructure for readability.
        messages = state.messages
        tool_use_context = state.toolUseContext
        turn_count = state.turnCount

        # Check max turns guard.
        if params.maxTurns is not None and turn_count > params.maxTurns:
            yield Terminal(reason="max_turns")
            return

        # ── Phase 3 — context preprocessing pipeline ────────────────────────
        # Four stages in source's order (src/query.ts:379→454). ORDER MATTERS:
        #
        #   1. snip_compact_if_needed   — documented stub. Source itself
        #      is a 17-line stub. Reports ``tokens_freed`` plumbed into
        #      autocompact's threshold; algorithm TBD post-Phase-5.
        #   2. microcompact             — DEFERRED no-op. Phase 3.3 was
        #      deferred — folding tool_results without prompt caching
        #      is strict context loss. See
        #      .cursor/rules/compaction-folding-deferred.mdc. Stage
        #      stays so the pipeline shape is reversible.
        #   3. apply_collapses_if_needed — DEFERRED no-op. Same reasoning
        #      as microcompact (lossy fold without caching offset). See
        #      same rule.
        #   4. autocompact              — LLM summary at ~80% threshold;
        #      returns ``(CompactionResult, new_consecutive_failures)``
        #      threaded through ``State`` (3.2 real).
        #
        # Source's pipeline started with ``applyToolResultBudget`` — a
        # disk-spill of oversized tool_results into ``<cwd>/.edwin/
        # tool_results/`` with an in-message marker pointing at the file.
        # That stage is removed in Edwin because the deployment target is
        # a multi-instance webapp: container filesystems are ephemeral
        # and instance-affined, so the spill would dangle across replicas
        # and rarely survive a restart. Tools cap their own response
        # sizes via ``maxResultSizeChars``; targeted readers (e.g.
        # ``ReadSlide``) avoid the giant-list-then-filter pattern that
        # made the spill necessary upstream.
        #
        # ``query_checkpoint`` events bracket the pipeline so chat-ui /
        # tests can observe stage boundaries without subscribing to each
        # stage's individual telemetry. Source emits these at the same
        # boundaries; we keep parity even though the 3.1 stages are
        # invisible to the user.
        messages_for_query: list["Message"] = list(messages)

        yield {"type": "query_checkpoint", "stage": "preprocess_start"}

        snip_result = snip_compact_if_needed(messages_for_query)
        messages_for_query = snip_result.messages
        yield {"type": "query_checkpoint", "stage": "snip_compact_done"}

        microcompact_result = await deps.microcompact(
            messages_for_query,
            tool_use_context,
        )
        messages_for_query = microcompact_result.messages
        yield {"type": "query_checkpoint", "stage": "microcompact_done"}

        collapse_result = await apply_collapses_if_needed(
            messages_for_query,
            tool_use_context,
        )
        messages_for_query = collapse_result.messages
        yield {"type": "query_checkpoint", "stage": "context_collapse_done"}

        # autocompact returns (result, new_consecutive_failures). The result
        # may carry a ``boundary`` to inject onto the message stream and a
        # ``kept_messages`` replacement; 3.1 stub returns no_op (skipped),
        # so neither happens. Wire-up is final.
        compaction_result, state.consecutive_autocompact_failures = await deps.autocompact(
            messages_for_query,
            tool_use_context,
            snip_tokens_freed=snip_result.tokens_freed,
            consecutive_failures=state.consecutive_autocompact_failures,
        )
        if not compaction_result.skipped:
            # Real compaction happened (3.2+ behavior) — replace the working
            # message list with the kept tail + summary, and emit the
            # boundary marker onto the SSE stream so chat-ui can render
            # the inline divider.
            messages_for_query = list(compaction_result.kept_messages)
            if compaction_result.boundary is not None:
                yield {
                    "type": "compact_boundary",
                    "boundary": compaction_result.boundary,
                }
            # Persist the compacted view back into State so subsequent
            # iterations don't re-do the work on stale messages.
            state.messages = messages_for_query

        yield {"type": "query_checkpoint", "stage": "preprocess_end"}

        # ── Phase 3.5 — context-fill warning hook ─────────────────────────
        # Runs after the pipeline so the warning reflects what the model
        # will actually see (post-spill, post-collapse). Fires at 70% of
        # the autocompact threshold (≈140K tokens against the default
        # 200K context window) — gives users a one-step heads-up before
        # autocompact starts taking action on its own.
        warning = compact_warning_hook(messages_for_query)
        if warning.should_show:
            yield {"type": "compact_warning", "warning": warning}

        # Re-bind ``messages`` to the post-pipeline view for the model call.
        messages = messages_for_query

        # Signal start of stream request.
        yield {"type": "stream_request_start"}

        # ── Call the model (wrapped in the recovery ladder) ───────────────
        # ``with_retry`` re-runs the factory on transient/recoverable
        # errors — but ONLY if no content has been yielded yet (otherwise
        # we'd duplicate text_deltas on the SSE wire). On a
        # ``prompt_too_long`` error pre-stream, the on_prompt_too_long
        # hook fires reactive_compact, swaps ``messages`` in this scope,
        # and signals the wrapper to re-attempt with the compacted list.
        assistant_messages: list["AssistantMessage"] = []

        async def _on_prompt_too_long() -> bool:
            # Reactive compaction. Mutates ``messages`` in the enclosing
            # scope so the next factory invocation picks up the
            # compacted list. Marks ``State.hasAttemptedReactiveCompact``
            # so the loop's final-error branch can distinguish "we
            # tried and failed" from "we never tried".
            #
            # Limitation (3.5): the reactive boundary is NOT emitted
            # onto the SSE stream — emitting between attempts would
            # require coupling ``with_retry`` to compaction types or
            # changing its contract to yield extra events from hooks.
            # The reactive path is a recovery, not user-visible by
            # design; the auto/manual paths still emit boundaries
            # normally. If/when chat-ui needs to surface reactive
            # recoveries explicitly, add a ``post_recover`` hook to
            # ``with_retry`` and emit there.
            nonlocal messages
            if state.hasAttemptedReactiveCompact:
                # Already tried this turn; declining means the wrapper
                # surfaces the original error rather than looping.
                return False
            state.hasAttemptedReactiveCompact = True
            result = await reactive_compact(messages, tool_use_context)
            if result.skipped:
                return False
            messages = list(result.kept_messages)
            state.messages = messages
            return True

        def _make_factory():
            # Capture the *current* ``messages`` at attempt time so a
            # reactive compact between attempts is reflected. Each
            # attempt invokes this and gets a fresh generator.
            def _factory():
                return deps.callModel(
                    messages=messages,
                    tools=params.tools,
                    model=tool_use_context.options.mainLoopModel,
                    system_prompt=params.systemPrompt,
                    thinking=tool_use_context.options.thinking,
                )

            return _factory

        try:
            async for event in with_retry(
                _make_factory(),
                on_prompt_too_long=_on_prompt_too_long,
            ):
                yield event
                if isinstance(event, dict) and event.get("type") == "assistant":
                    assistant_messages.append(event)  # type: ignore[arg-type]
        except NotImplementedError:
            yield Terminal(reason="model_error", detail="callModel not implemented (Phase 1.3)")
            return
        except MaxRetriesExceeded as e:
            yield Terminal(reason="model_error", detail=f"Max retries exceeded: {e}")
            return
        except Exception as e:  # noqa: BLE001
            yield Terminal(reason="model_error", detail=str(e))
            return

        # ── Append assistant messages to state ──────────────────────────────
        state.messages = state.messages + assistant_messages

        # ── Extract tool uses ───────────────────────────────────────────────
        all_tool_uses: list[dict[str, Any]] = []
        for am in assistant_messages:
            all_tool_uses.extend(_extract_tool_uses(am))

        # ── Termination: no tool uses → completed ───────────────────────────
        if not all_tool_uses:
            yield Terminal(reason="completed")
            return

        # ── Tool execution ──────────────────────────────────────────────────
        # Phase A: concurrency-safe backend tools run as asyncio.gather
        # chunks, unsafe ones run sequentially. Order of the original
        # tool_use blocks is preserved in `tool_results` so the model sees a
        # coherent turn history — only wall-clock overlaps, never logical
        # reordering. Interactive tools (requires_user_interaction) still
        # use the legacy singular `tool_request` envelope; batching those is
        # Phase B.
        tool_results: list["UserMessage"] = []
        parent = assistant_messages[-1] if assistant_messages else {}

        # Scan blocks in order; group consecutive safe ones into parallel
        # chunks; unsafe ones run solo. Stop at the first interactive tool
        # and hand off to the frontend batched tool_request flow.
        i = 0
        first_interactive_idx: int | None = None
        while i < len(all_tool_uses):
            tu = all_tool_uses[i]
            tool = find_tool_by_name(params.tools, tu.get("name", ""))

            if _is_interactive(tool):
                first_interactive_idx = i
                break

            # Collect a run of consecutive concurrency-safe tools. Stops at
            # an unsafe tool or an interactive tool so side-effects of
            # mutators are visible to later reads.
            if _is_safe(tool, tu.get("input", {})):
                j = i
                while j < len(all_tool_uses):
                    ntu = all_tool_uses[j]
                    ntool = find_tool_by_name(params.tools, ntu.get("name", ""))
                    if _is_interactive(ntool):
                        break
                    if not _is_safe(ntool, ntu.get("input", {})):
                        break
                    j += 1
                chunk = all_tool_uses[i:j]

                if len(chunk) == 1:
                    # Single safe tool — no need for the funnel machinery.
                    async for ev in _execute_single_tool(
                        chunk[0],
                        params.tools,
                        tool_use_context,
                        params.canUseTool,
                        parent,
                    ):
                        yield ev
                        if isinstance(ev, dict) and ev.get("type") == "user":
                            tool_results.append(ev)  # type: ignore[arg-type]
                else:
                    # Parallel chunk: funnel events through a queue; bucket
                    # tool_result UserMessages per-tool to preserve order.
                    buckets: list[list["UserMessage"]] = [[] for _ in chunk]
                    async for idx, ev in _run_parallel_chunk(
                        chunk,
                        params.tools,
                        tool_use_context,
                        params.canUseTool,
                        parent,
                    ):
                        yield ev
                        if isinstance(ev, dict) and ev.get("type") == "user":
                            buckets[idx].append(ev)  # type: ignore[arg-type]
                    for b in buckets:
                        tool_results.extend(b)
                i = j
                continue

            # Unsafe backend tool — run solo, serial.
            async for ev in _execute_single_tool(
                tu,
                params.tools,
                tool_use_context,
                params.canUseTool,
                parent,
            ):
                yield ev
                if isinstance(ev, dict) and ev.get("type") == "user":
                    tool_results.append(ev)  # type: ignore[arg-type]
            i += 1

        # ── Interactive handoff: batched tool_request envelope ──────────────
        # All interactive tools from the first interactive to the end of the
        # assistant message are collected here and partitioned by
        # is_concurrency_safe. Any non-interactive tools emitted after the
        # first interactive are dropped (same behavior as the pre-Phase-B
        # loop) — the model can re-emit them next turn with the interactive
        # answers as prior_tool_results.
        if first_interactive_idx is not None:
            parallel_calls: list[dict[str, Any]] = []
            sequential_calls: list[dict[str, Any]] = []
            interactive_calls: list[tuple[str, str]] = []
            for j in range(first_interactive_idx, len(all_tool_uses)):
                tu = all_tool_uses[j]
                tool = find_tool_by_name(params.tools, tu.get("name", ""))
                if not _is_interactive(tool):
                    continue
                call = {
                    "tool_use_id": tu.get("id", ""),
                    "tool_name": tu.get("name", ""),
                    "tool_input": tu.get("input", {}),
                }
                interactive_calls.append((tu.get("id", ""), tu.get("name", "")))
                if _is_safe(tool, tu.get("input", {})):
                    parallel_calls.append(call)
                else:
                    sequential_calls.append(call)

            prior_results = []
            for tr in tool_results:
                for b in tr.get("message", {}).get("content", []):
                    if b.get("type") == "tool_result":
                        prior_results.append(
                            {
                                "call_id": b.get("tool_use_id", ""),
                                "output": b.get("content", ""),
                                "success": not b.get("is_error", False),
                            }
                        )

            # ``tool_call_complete`` — symmetric with the non-interactive
            # path (``_execute_single_tool``'s ``finally``). Backend-
            # executed tools emit one per call after their real
            # execution; interactive tools have no real execution on
            # the backend (the work is hand-off to the user), so we
            # emit at the hand-off boundary — right before the
            # tool_request envelope. The FE consumes this via
            # ``TOOL_CALL_COMPLETE`` to seal the per-tool spinner the
            # same way it does for every other tool. Without these
            # events, AskUserQuestion's tool block would only get
            # sealed by the leg-end ``STREAM_DONE`` fallback (later
            # and less precise).
            for tool_use_id, tool_name in interactive_calls:
                yield {
                    "type": "tool_call_complete",
                    "call_id": tool_use_id,
                    "name": tool_name,
                    "success": True,
                }

            yield {
                "type": "tool_request",
                "parallel_calls": parallel_calls,
                "sequential_calls": sequential_calls,
                "prior_tool_results": prior_results,
            }
            yield Terminal(reason="tool_request")
            return

        # ── Append tool results to state ────────────────────────────────────
        state.messages = state.messages + tool_results

        # ── Continue to next iteration ──────────────────────────────────────
        state.turnCount += 1
        state.transition = Continue(reason="tool_cycle")
