"""
``autoCompact`` — threshold-driven LLM summarization (Layer 1).

Source: src/services/compact/autoCompact.ts (351 lines).

Phase 3.2: real implementation. Threshold-checks the input messages
against the configured ``AUTO_COMPACT_THRESHOLD_TOKENS``; if over,
calls ``compact_conversation`` (the LLM summarizer) and returns the
result. On exception, increments the threaded ``consecutive_failures``
counter so a future Phase 3.5 retry-ladder can downgrade after N
successive failures.

Return contract (locked in 3.1, unchanged here):
  ``(CompactionResult, new_consecutive_failures)``

The query loop (``query_loop._query_body``) reads
``compaction_result.skipped`` to decide whether to inject the boundary
event onto the SSE stream and replace ``state.messages``. So skipping
is just "return a no_op CompactionResult"; the loop handles the rest.

# TODO(3.5): emit ``compact_telemetry`` SSE event (analytics parity
# with source's tengu_post_autocompact_turn). Field shape TBD with the
# observability surface in 3.6.
"""

from __future__ import annotations

from typing import Any

from app_logger import get_logger

from app.config import get_settings

from ..token_estimation import estimate_messages_tokens
from .compact import compact_conversation
from .types import AutocompactReturn, CompactionResult

log = get_logger(__name__)


# ── Threshold ──────────────────────────────────────────────────────────────

# 80% of a 200K-token context window. Plan said "~80% of context window";
# choosing the larger Claude-3-class context as the floor keeps us from
# false-positively triggering compaction on shorter-context models that
# can swallow the same conversation comfortably. When the model resolver
# learns about per-model context windows, this constant moves to a
# per-context-window calculation.
# # TUNE: source-parity unknown.
_DEFAULT_AUTO_COMPACT_THRESHOLD_TOKENS = 160_000

# Env override: ``EDWIN_AUTOCOMPACT_THRESHOLD_TOKENS`` in ``backend/.env``
# (loaded via ``app.config``). ``0`` keeps the production default;
# anything > 0 replaces it. This exists so the autocompact path can be
# exercised on tiny conversations during local testing without
# rebuilding the image. Read once at module load, on purpose — the
# threshold is logged at startup so it's visible in the boot trace.
_override = get_settings().compaction.autocompact_threshold_tokens
AUTO_COMPACT_THRESHOLD_TOKENS = (
    _override if _override > 0 else _DEFAULT_AUTO_COMPACT_THRESHOLD_TOKENS
)
if _override > 0:
    log.warning(
        "autocompact threshold overridden via EDWIN_AUTOCOMPACT_THRESHOLD_TOKENS: %d (default %d)",
        _override,
        _DEFAULT_AUTO_COMPACT_THRESHOLD_TOKENS,
    )


# ── Public entrypoint ─────────────────────────────────────────────────────


async def autocompact(
    messages: list[Any],
    ctx: Any = None,
    *,
    snip_tokens_freed: int = 0,
    consecutive_failures: int = 0,
    manual: bool = False,
) -> AutocompactReturn:
    """Threshold-aware compaction.

    Args:
      messages: pipeline-stage input — already passed through
        ``apply_tool_result_budget``, ``snip_compact_if_needed``,
        ``microcompact``, and ``apply_collapses_if_needed``.
      ctx: ``ToolUseContext`` for model resolution + auth. None in tests.
      snip_tokens_freed: tokens freed by the snip stage. The threshold
        check subtracts this from the estimated total so a successful
        snip can suppress an unnecessary autocompact.
      consecutive_failures: count threaded across iterations via
        ``State.consecutive_autocompact_failures``. Reset to 0 on
        success; bumped on exception.
      manual: True iff invoked by ``/compact`` — bypasses the threshold
        check, forces a compaction unconditionally.

    Returns:
      ``(result, new_consecutive_failures)`` where:
        - ``result.skipped == True``  → loop does nothing
        - ``result.skipped == False`` → loop replaces messages, emits
          boundary event onto the SSE stream
    """
    if not manual:
        tokens = estimate_messages_tokens(messages) - snip_tokens_freed
        if tokens <= AUTO_COMPACT_THRESHOLD_TOKENS:
            # Under threshold — do nothing. Don't touch the failure
            # counter; threshold-skip is an expected non-event, not a
            # success or failure of the summarizer.
            return CompactionResult.no_op(), consecutive_failures
        log.info(
            "autocompact firing: tokens=%d threshold=%d (snip_freed=%d, prior_failures=%d)",
            tokens,
            AUTO_COMPACT_THRESHOLD_TOKENS,
            snip_tokens_freed,
            consecutive_failures,
        )

    try:
        result = await compact_conversation(messages, ctx, manual=manual)
    except Exception as e:  # noqa: BLE001
        new_failures = consecutive_failures + 1
        log.exception(
            "autocompact failed (consecutive_failures %d → %d): %s",
            consecutive_failures,
            new_failures,
            e,
        )
        # Return a no_op result so the loop continues with the original
        # messages. The next iteration may retry; Phase 3.5's with_retry
        # ladder will eventually downgrade or surface a clean error.
        return CompactionResult.no_op(), new_failures

    # Success — reset the failure counter. ``compact_conversation`` may
    # itself return a skipped result (e.g. degenerate split point) — in
    # that case there's nothing to do but the call succeeded, so the
    # counter still resets. Source has the same behavior: a successful
    # threshold-check-but-nothing-to-summarize doesn't accumulate failures.
    return result, 0


__all__ = ["autocompact", "AUTO_COMPACT_THRESHOLD_TOKENS"]
