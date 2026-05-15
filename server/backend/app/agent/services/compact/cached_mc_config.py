"""
Cached microcompact configuration — knobs for the cache-stable variant.

Source: src/services/compact/cachedMCConfig.ts (3 lines).

The cached microcompact path (Phase 3.3 ``cached_microcompact.py``)
keys its work by ``tool_use_id`` so that *identical* input message
arrays produce *identical* output edits — that's what lets prompt-cache
remain hot across turns. This module holds the toggles that variant
needs.

Source's 3-line file is essentially:

    export const CACHED_MC_CONFIG = {
      enabled: true,
      keyByToolUseId: true,
    };

We mirror that as a frozen dataclass so callers ``from
cached_mc_config import CONFIG`` and read ``CONFIG.enabled``. Frozen
because runtime mutation of a config singleton is a category of bug
we don't want.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CachedMCConfig:
    """Knobs for ``cached_microcompact``."""

    enabled: bool = True
    # Key cache entries by tool_use_id (the only id that's content-stable
    # across replays). False would key by content hash, defeating cache
    # stability — kept as a knob for parity with source, not a tuning
    # surface we expect anyone to flip.
    key_by_tool_use_id: bool = True


CONFIG = CachedMCConfig()


__all__ = ["CachedMCConfig", "CONFIG"]
