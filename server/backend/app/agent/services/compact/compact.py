"""
Compaction orchestrator — runs the LLM summarize and assembles the
``CompactionResult``.

Source: src/services/compact/compact.ts (1708 lines).

This is the heaviest single port in Phase 3 and the one with the most
source-parity risk under the source-from-plan-only constraint. The
plan's prose specifies the call shape, output shape, and a few
invariants ("never split a tool_use/tool_result pair across the
boundary", "tokens before/after metrics") but doesn't specify:

  - exact split-point algorithm (how many tail messages to keep)
  - which messages count as "critical files" worth retaining verbatim
  - retry/fallback if the LLM call itself fails mid-summarize

For the choices below see the per-helper docstrings; each non-obvious
decision is flagged ``# TUNE``.

Implementation outline:

  1. ``find_split_point`` — walk backwards from the end; collect a
     tail of N turn-pairs; expand the cut to never split a
     tool_use/tool_result pair.
  2. ``_summarize`` — call the LLM with the COMPACTION_SYSTEM_PROMPT
     and a transcript of the to-summarize portion; accumulate text
     deltas into a single string.
  3. ``_synthesize_summary_message`` — wrap the LLM's summary text in
     a loop-shape message that the next turn's model will see as a
     plain user message tagged ``compact_summary``.
  4. ``_make_boundary`` — build the immutable ``CompactBoundary`` for
     the SSE stream and the kept-tail front matter.
  5. Compose ``CompactionResult.kept_messages = [summary_msg, *kept_tail]``.

The orchestrator stays *unwired* from db persistence. Replacing
``state.messages`` is the query loop's job (already wired in 3.1);
persisting the boundary back to db is a separate concern (the
``conversations`` table is append-only per the architecture rule and
true history-replacement needs a schema change — flagged as
TODO(post-3.2) in the /compact slash command).
"""

from __future__ import annotations

from typing import Any, Mapping

from app_logger import get_logger

from ..api.claude import query_model_with_streaming
from ..token_estimation import estimate_messages_tokens
from .grouping import find_tool_pairs
from .prompt import (
    COMPACTION_SYSTEM_PROMPT,
    build_compact_user_message,
    render_transcript,
)
from .types import CompactBoundary, CompactionResult

log = get_logger(__name__)


# ── Tunable retention parameters ───────────────────────────────────────────

# Number of "turn pairs" (one user → one assistant) kept verbatim at the
# tail. The split point lands BEFORE this many pairs (counted from end).
# Plan said "keep last N tool_results, keep critical files". We translate
# that into turn-pairs because that's the natural conversation boundary;
# the count of tool_results inside those pairs varies with how
# tool-heavy the recent turns were.
# # TUNE: source-parity unknown.
KEEP_TAIL_TURN_PAIRS = 3

# Lower bound: even a brand-new conversation that triggered a manual
# /compact should keep at least the last user message and any pending
# tool_results bound to the current turn's tool_uses.
# # TUNE: source-parity unknown.
MIN_KEEP_TAIL_MESSAGES = 2


# ── Split-point logic ─────────────────────────────────────────────────────


def find_split_point(messages: list[Any]) -> int:
    """Return the index ``i`` such that ``messages[:i]`` is summarized
    and ``messages[i:]`` is kept verbatim.

    Algorithm:
      1. Walk backwards counting role-transitions until we've seen
         ``KEEP_TAIL_TURN_PAIRS`` user→assistant transitions OR we
         hit the start of the message list.
      2. The split point is right BEFORE the earliest message of the
         kept window.
      3. Pair-integrity adjustment: if the split would land between a
         tool_use and its tool_result (i.e. one is in the to-summarize
         half and the other is in the kept half), move the split
         EARLIER so both end up in the kept tail. We never move the
         split LATER (that would drop a tool_result whose tool_use is
         already kept — also broken, but the symmetric direction).
      4. Floor at ``len(messages) - MIN_KEEP_TAIL_MESSAGES`` and
         ceiling at 0 — never returns an index that would summarize
         everything or summarize nothing.

    Returns:
      ``i`` in ``[0, len(messages)]``. ``i == 0`` means "summarize
      nothing"; ``i == len(messages)`` means "summarize everything".
      The autocompact threshold check guarantees we only call this
      when there's enough to summarize, so degenerate edges are rare
      but defensible.
    """
    n = len(messages)
    if n == 0:
        return 0

    # Step 1: count turn-pairs walking backwards.
    pairs_seen = 0
    saw_user_after_assistant = False
    cut = n
    for idx in range(n - 1, -1, -1):
        msg = messages[idx]
        role = _msg_role(msg)
        if role == "assistant":
            # Reset latch — we're now waiting for the user that PROMPTED
            # this assistant turn.
            saw_user_after_assistant = False
        elif role == "user" and not saw_user_after_assistant:
            # A user→assistant pair just closed (we saw the assistant first
            # walking backwards, now we see its user).
            saw_user_after_assistant = True
            pairs_seen += 1
            if pairs_seen >= KEEP_TAIL_TURN_PAIRS:
                cut = idx
                break

    # If we exhausted messages without hitting the pair count, keep
    # everything (cut at 0 means summarize nothing — conservative).
    if pairs_seen < KEEP_TAIL_TURN_PAIRS:
        cut = 0

    # Step 2: pair-integrity. Walk all tool_use/tool_result pairs; if
    # any cross the split, slide the split earlier so the pair stays
    # together in the kept tail.
    cut = _adjust_for_pair_integrity(messages, cut)

    # Step 3: floor + ceiling.
    cut = max(0, min(cut, max(0, n - MIN_KEEP_TAIL_MESSAGES)))
    return cut


def _msg_role(msg: Any) -> str:
    """Loose role extraction. Source uses normalized message types; we
    handle both the wrapped and bare shapes."""
    if not isinstance(msg, Mapping):
        return ""
    inner = msg.get("message")
    if isinstance(inner, Mapping):
        return str(inner.get("role") or msg.get("type") or "")
    return str(msg.get("role") or msg.get("type") or "")


def _adjust_for_pair_integrity(messages: list[Any], cut: int) -> int:
    """Walk every tool_use/tool_result pair; if a pair straddles
    ``cut`` (use-msg-idx < cut <= result-msg-idx, or vice versa),
    slide ``cut`` to the smaller index of the two so the pair lives
    entirely in the kept tail.

    Never move the cut later — that risks dropping a tool_result
    whose tool_use was already in the kept tail, which is also a
    broken pair but in the opposite direction. Conservative choice.
    """
    pairs = find_tool_pairs(messages)
    new_cut = cut
    for p in pairs:
        if p.message_result_idx is None:
            # Orphan tool_use — post_compact_cleanup will drop it.
            continue
        use_m = p.message_use_idx
        res_m = p.message_result_idx
        # The pair straddles the boundary if one msg-idx is strictly
        # less than ``new_cut`` and the other is >= ``new_cut``.
        if (use_m < new_cut <= res_m) or (res_m < new_cut <= use_m):
            new_cut = min(new_cut, use_m, res_m)
    return new_cut


# ── LLM summarization call ────────────────────────────────────────────────


async def _summarize(
    messages_to_summarize: list[Any],
    ctx: Any,
    *,
    manual: bool,
) -> str:
    """Call the LLM with COMPACTION_SYSTEM_PROMPT + transcript; return
    the assembled summary text.

    Uses the same ``query_model_with_streaming`` entrypoint as the main
    loop so provider routing / auth / proxy config are reused. Tools
    are intentionally None — the summarizer should only emit text.
    Thinking is disabled — we don't want chain-of-thought tokens in
    the cost ledger for summarization.

    Failures bubble; ``autocompact`` catches and bumps the failure
    counter.
    """
    transcript = render_transcript(messages_to_summarize)
    user_text = build_compact_user_message(transcript, manual=manual)

    # Wrap as a single user message in the loop's expected shape.
    summarize_messages = [{
        "type": "user",
        "message": {
            "role": "user",
            "content": [{"type": "text", "text": user_text}],
        },
    }]

    model = ""
    if ctx is not None:
        opts = getattr(ctx, "options", None)
        if opts is not None:
            model = getattr(opts, "mainLoopModel", "") or ""

    text_parts: list[str] = []
    async for event in query_model_with_streaming(
        messages=summarize_messages,
        tools=None,
        model=model,
        system_prompt=COMPACTION_SYSTEM_PROMPT,
        thinking=False,
    ):
        if not isinstance(event, dict):
            continue
        etype = event.get("type")
        if etype == "text_delta":
            text_parts.append(event.get("text") or "")
        # We deliberately ignore tool_call_* events — the summarizer
        # shouldn't emit any. If it does (model misbehavior), we just
        # drop them and use whatever text was emitted.
        elif etype == "assistant":
            # Final assistant message arrived — extract its text content
            # as a fallback if no text_delta events fired (some adapters
            # batch deltas only at the end).
            inner = event.get("message")
            if isinstance(inner, Mapping):
                content = inner.get("content")
                if isinstance(content, list):
                    for b in content:
                        if isinstance(b, Mapping) and b.get("type") == "text":
                            t = b.get("text") or ""
                            if t and t not in text_parts:
                                text_parts.append(t)
        # 'done' / others — ignore.

    summary = "".join(text_parts).strip()
    if not summary:
        # The summarizer returned nothing useful. Bubble as a runtime
        # error so autocompact's exception path bumps the failure
        # counter rather than silently shipping an empty boundary.
        raise RuntimeError("Compaction summarizer returned empty body")
    return summary


# ── Result assembly ────────────────────────────────────────────────────────


def _synthesize_summary_message(summary: str) -> dict[str, Any]:
    """Wrap the LLM's summary text in a loop-shape user message. Marked
    with ``isCompactSummary: True`` so chat-ui (and downstream tools)
    can render it specially without sniffing content.

    Why a *user* message, not assistant: the next turn's assistant
    needs to read the summary as authoritative prior context — same
    role it would treat the user's earlier messages. Marking it
    assistant would conflate it with the assistant's own prior turns.
    """
    return {
        "type": "user",
        "isCompactSummary": True,
        "message": {
            "role": "user",
            "content": [{
                "type": "text",
                "text": (
                    "[Prior conversation summarized for context. "
                    "Treat this as authoritative history.]\n\n"
                    + summary
                ),
            }],
        },
    }


def _make_boundary(
    *,
    summary: str,
    tokens_before: int,
    tokens_after: int,
    dropped_count: int,
    manual: bool,
) -> CompactBoundary:
    """Build the immutable boundary marker emitted onto the SSE stream
    and embedded in the result. ``compacted_at`` is set by the dataclass
    default."""
    return CompactBoundary(
        tokens_before=tokens_before,
        tokens_after=tokens_after,
        dropped_count=dropped_count,
        summary=summary,
        manual=manual,
    )


# ── Public entrypoint ─────────────────────────────────────────────────────


async def compact_conversation(
    messages: list[Any],
    ctx: Any = None,
    *,
    manual: bool = False,
) -> CompactionResult:
    """Run a full compaction pass on ``messages`` and return the result.

    This is the function ``autoCompact`` and ``reactiveCompact`` both
    delegate to. ``manual=True`` flag is passed through to the prompt
    and the boundary so the user-facing copy can distinguish "you ran
    /compact" from "context was getting full".

    Args:
      messages: full message list to compact.
      ctx: ``ToolUseContext`` for model resolution. May be None in tests.
      manual: True iff invoked by ``/compact``.

    Returns:
      ``CompactionResult`` with ``skipped=False``, ``boundary`` populated,
      and ``kept_messages = [summary_message, *kept_tail]``.

    Raises:
      Any exception from the LLM call. Callers (``autoCompact``) catch
      and convert to a no_op result + failure-counter bump.
    """
    n = len(messages)
    if n == 0:
        # Degenerate — nothing to summarize. Return a skipped result.
        return CompactionResult.no_op()

    tokens_before = estimate_messages_tokens(messages)

    cut = find_split_point(messages)
    to_summarize = messages[:cut]
    kept_tail = messages[cut:]

    if not to_summarize:
        # Nothing crosses the boundary — either the conversation is
        # too short or pair-integrity adjustments collapsed the cut to
        # zero. Either way, no summary to produce.
        return CompactionResult.no_op()

    log.info(
        "compact_conversation manual=%s n_msgs=%d cut=%d to_summarize=%d kept=%d tokens_before=%d",
        manual, n, cut, len(to_summarize), len(kept_tail), tokens_before,
    )

    summary = await _summarize(to_summarize, ctx, manual=manual)
    summary_msg = _synthesize_summary_message(summary)

    # Run cleanup on the kept tail before assembling the result. This
    # ensures the pair-repair pass sees the FINAL kept set (the summary
    # message has no tool_use/tool_result blocks so it can't introduce
    # orphans).
    from .post_compact_cleanup import post_compact_cleanup  # late import for cycle safety  # noqa: PLC0415
    cleaned_tail = post_compact_cleanup(kept_tail)

    new_messages: list[Any] = [summary_msg, *cleaned_tail]
    tokens_after = estimate_messages_tokens(new_messages)

    boundary = _make_boundary(
        summary=summary,
        tokens_before=tokens_before,
        tokens_after=tokens_after,
        dropped_count=len(to_summarize),
        manual=manual,
    )

    return CompactionResult(
        summary=summary,
        boundary=boundary,
        kept_messages=new_messages,
        dropped_count=len(to_summarize),
        tokens_before=tokens_before,
        tokens_after=tokens_after,
        skipped=False,
    )


__all__ = [
    "compact_conversation",
    "find_split_point",
    "KEEP_TAIL_TURN_PAIRS",
    "MIN_KEEP_TAIL_MESSAGES",
]
