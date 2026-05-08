"""
Context collapse — fold consecutive Read/Search/List tool batches into
a single placeholder message.

**STATUS: DEFERRED no-op.** See `.cursor/rules/compaction-folding-deferred.mdc`.

Phase 3.4's ``apply_collapses_if_needed`` (the real algorithm) was
evaluated on 2026-04-29 and deferred indefinitely along with
microCompact. Both stages do lossy content rewrites that rely on
prompt caching to recoup the lost context across turns; Edwin
doesn't ship caching, so folding is a strict downgrade vs.
``autoCompact``'s LLM-summarize.

**Trigger to revisit:** Edwin ships prompt caching. Until then, leave
this as the no-op below.

Why the file still exists:

  - The 5-stage pipeline in ``query_loop.py`` calls this stage every
    turn; keeping the stub keeps the pipeline shape stable so the
    decision is reversible.
  - ``CollapseResult`` is a typed contract used by the loop — flipping
    the bodies in/out without re-typing call sites means the swap
    when caching lands is mechanical.

The plan's *intended* behavior, preserved here for posterity:

  1. ``services.compact.grouping.find_collapse_groups`` detects
     clusters of consecutive Read/Search/List tool_uses inside a
     single assistant message.
  2. Each cluster is replaced with a ``collapsed_read_search`` message
     that preserves the tool_use_id list (for replay safety) but
     folds all the result content into a one-paragraph summary
     placeholder.
  3. Per source (query.ts:429-441): runs BEFORE autocompact so that
     if collapse gets us under threshold, autocompact is a no-op.

If revisited, ``find_collapse_groups`` is already implemented in
``services/compact/grouping.py`` — only the rewriter logic needs to
land here.
"""

from __future__ import annotations

from typing import Any

from ..services.compact.types import CollapseResult


async def apply_collapses_if_needed(
    messages: list[Any],
    _ctx: Any = None,
) -> CollapseResult:
    """Identity pass-through. See module docstring for why this is
    deferred. Returns input messages unchanged with ``collapsed_count=0``.
    """
    return CollapseResult(messages=messages, collapsed_count=0)


__all__ = ["apply_collapses_if_needed"]
