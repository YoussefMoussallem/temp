"""
``microCompact`` — rule-based truncation (Layer 2 main).

**STATUS: DEFERRED no-op.** See `.cursor/rules/compaction-folding-deferred.mdc`.

Phase 3.3 (the full port of source's 530-LoC ``microCompact.ts`` plus
the 153-LoC ``apiMicrocompact.ts`` plus the 37-LoC
``cachedMicrocompact.ts``) was evaluated on 2026-04-29 and deferred
indefinitely. microCompact's three core operations all rewrite
tool_result content lossy-style:

  1. Truncate redundant tool_results (same ``tool_use_id`` referenced N
     times → keep last full, fold earlier to previews).
  2. Dedup repeated Reads — older calls become previews.
  3. Fold collapsed read/search groups → summary placeholder.

In Anthropic's reference impl these pay off because the cache-stable
variant (``cachedMicrocompact``) keeps prompt cache hot across turns —
the win is cache hit-rate, not token count. Edwin's LLM proxy doesn't
expose prompt caching, so the only remaining motivation is raw token
reduction — and ``autoCompact`` (Phase 3.2) does that better with an
LLM-summarize that preserves intent. Lossy folding doesn't.

**Trigger to revisit:** Edwin ships prompt caching. Until then, do
not add real folding logic here — the rule is the contract; this
file is the shadow.

Why the file still exists:

  - The 5-stage pipeline in ``query_loop.py`` is structurally fixed
    at 3.1; keeping the stage as a no-op means the pipeline shape
    doesn't drift if Edwin ever ships prompt caching and the decision
    flips.
  - ``deps.microcompact`` in ``QueryDeps`` keeps the same call
    signature so tests can inject behaviour-altering microcompacts
    without refactoring the rest of the pipeline.
"""

from __future__ import annotations

from typing import Any

from .types import MicrocompactResult


async def microcompact(
    messages: list[Any],
    _ctx: Any = None,
) -> MicrocompactResult:
    """Identity pass-through. See module docstring for why this is
    deferred. Returns the input messages unchanged with no
    ``compaction_info`` so the pipeline reports "nothing happened"
    cleanly to telemetry.
    """
    return MicrocompactResult(messages=messages, compaction_info=None)


__all__ = ["microcompact"]
