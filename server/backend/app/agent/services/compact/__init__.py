"""Compaction package — barrel-only re-exports.

Per ``feedback_init_barrel_only`` constraint: ``__init__.py`` files
hold no logic, only re-exports. The five preprocessing stages
(``snip_compact``, ``microcompact``, ``autocompact``, plus the two
helpers ``apply_tool_result_budget`` and ``apply_collapses_if_needed``)
are wired by the query loop directly from their submodules so this
barrel doesn't need to re-export *all* of them — just the type
contracts that downstream callers (chat-ui via SSE, command handlers
via /compact, future Phase 3.5 retry ladder) depend on.

Submodules:

  - ``types``                 — CompactionResult, CompactionInfo,
                                 CompactBoundary, SnipResult,
                                 MicrocompactResult, CollapseResult,
                                 AutocompactReturn
  - ``snip_compact``          — Layer 2 supporting (documented stub —
                                 source is also a stub; algorithm TBD)
  - ``micro_compact``         — Layer 2 main      DEFERRED no-op
                                 (Phase 3.3 deferred — see
                                 .cursor/rules/compaction-folding-deferred.mdc)
  - ``auto_compact``          — Layer 1           (3.2 real)
  - ``compact``               — orchestrator (compact_conversation)   (3.2)
  - ``prompt``                — COMPACTION_SYSTEM_PROMPT + transcript (3.2)
  - ``post_compact_cleanup``  — pair repair, thinking strip, cache    (3.2)
  - ``reactive_compact``      — force-fire wrapper for prompt_too_long (3.2)
  - ``snip_projection``       — projection helper for snipCompact
  - ``cached_mc_config``      — knobs for cached microcompact (3.3)
  - ``time_based_mc_config``  — debounce / interval gating (3.3)
  - ``grouping``              — pair + collapse-group helpers
"""

from .auto_compact import AUTO_COMPACT_THRESHOLD_TOKENS, autocompact
from .compact import compact_conversation
from .post_compact_cleanup import post_compact_cleanup
from .reactive_compact import reactive_compact
from .types import (
    AutocompactReturn,
    CollapseResult,
    CompactBoundary,
    CompactionInfo,
    CompactionResult,
    MicrocompactResult,
    SnipResult,
)

__all__ = [
    "AUTO_COMPACT_THRESHOLD_TOKENS",
    "AutocompactReturn",
    "CollapseResult",
    "CompactBoundary",
    "CompactionInfo",
    "CompactionResult",
    "MicrocompactResult",
    "SnipResult",
    "autocompact",
    "compact_conversation",
    "post_compact_cleanup",
    "reactive_compact",
]
