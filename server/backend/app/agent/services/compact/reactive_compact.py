"""
``reactiveCompact`` — force-fire compaction on prompt_too_long mid-turn.

Source: src/services/compact/reactiveCompact.ts (22 lines).

When the LLM call raises a ``prompt_too_long`` error mid-turn (i.e.
after the auto-compact threshold check passed but the model rejects
the prompt anyway — usually because tool_results bloated more than
estimation predicted), the recovery ladder calls this function to
force-fire compaction *bypassing* the threshold check.

Phase 3.2: implements the function. Phase 3.5 wires it into
``with_retry``'s recovery ladder. Until 3.5, the function is callable
but has no caller — it's exported for tests and so 3.5's wire-up
doesn't require touching this module.

Distinction from ``autocompact(manual=True)``:

  - ``autocompact(manual=True)`` is the ``/compact`` slash-command path.
    It runs as a normal pipeline stage; success/failure flows through
    the failure counter; the boundary lands on the SSE stream.
  - ``reactiveCompact`` is the recovery path — it's invoked from
    *inside* the model-call error handler, AFTER the LLM has already
    failed once. The counter semantics differ (a reactive compaction
    isn't a "failure to summarize" — it's "the model couldn't accept
    the prompt"), so we keep the entry points separate.

Both delegate to ``compact_conversation`` for the actual work, so the
boundary, summary, and kept_messages shape are identical.
"""

from __future__ import annotations

from typing import Any

from app_logger import get_logger

from .compact import compact_conversation
from .post_compact_cleanup import post_compact_cleanup
from .types import CompactionResult

log = get_logger(__name__)


async def reactive_compact(
    messages: list[Any],
    ctx: Any = None,
) -> CompactionResult:
    """Force-fire compaction. No threshold check.

    Returns the ``CompactionResult`` so the caller (3.5 ``with_retry``)
    can:
      - take ``result.kept_messages`` as the messages for the retry
      - emit ``result.boundary`` onto the SSE stream so chat-ui sees
        the compaction
      - log ``result.tokens_before`` / ``result.tokens_after`` for the
        retry's instrumentation

    Why not return just the messages: future 3.6 chat-ui needs the
    boundary for inline rendering, and 3.5 needs the token counts for
    retry-ladder telemetry. Returning the full result keeps the
    contract uniform with ``autocompact``.

    Raises:
      Any exception from the LLM call. The caller is responsible for
      escalating: typically falls through the recovery ladder to
      "abort with clean error" rather than retrying compaction.
    """
    log.info(
        "reactive_compact firing: n_msgs=%d (recovery from prompt_too_long)",
        len(messages),
    )
    result = await compact_conversation(messages, ctx, manual=False)
    if result.skipped:
        # Edge: split-point logic decided not to compact (degenerate
        # conversation, or pair-integrity collapsed the cut to zero).
        # Don't loop reactively — caller should escalate.
        log.warning("reactive_compact: compact_conversation skipped — nothing to compact")
        return result

    # Belt-and-braces cleanup. compact_conversation already runs
    # ``post_compact_cleanup`` on the kept tail before returning, but
    # in the reactive path we additionally re-run it to handle the
    # case where the synthesized summary message accidentally ended
    # up in a state needing cleanup (e.g. with cache_control inherited
    # from a wrapper). Idempotent — running twice is safe.
    result.kept_messages = post_compact_cleanup(result.kept_messages)
    return result


__all__ = ["reactive_compact"]
