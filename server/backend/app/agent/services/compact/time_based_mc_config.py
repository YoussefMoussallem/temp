"""
Time-based microcompact configuration — debounce + minimum-interval knobs.

Source: src/services/compact/timeBasedMCConfig.ts (43 lines).

``microcompact`` runs every turn, but its real work — folding repeated
reads, deduping tool_results — is wasted if the model just wrote
fresh content (the new content can't yet be a duplicate of itself).
Source's time-based config gates the heavy passes:

  - Don't run the dedup pass more than once per ``min_interval_secs``.
  - On a "cold" turn (no prior microcompact), run unconditionally.
  - When configured ``aggressiveness`` is "low", widen the interval
    to amortize across more turns.

Phase 3.1 ships the configuration shape and a ``should_run_now`` predicate
that returns True (= "always run", matches the 3.1 stub semantics where
microcompact is itself a no-op). Phase 3.3 swaps in the real predicate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


Aggressiveness = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class TimeBasedMCConfig:
    """Knobs for the time-based gating of microcompact's heavy passes.

    All durations in **seconds**. Source uses milliseconds; we convert
    once at the boundary so internal arithmetic stays in float seconds
    (the unit ``time.monotonic()`` returns).

    Defaults are chosen to never gate microcompact in 3.1 — once 3.3
    lands and the heavy passes have real cost, the defaults shift to
    "medium aggressiveness" with a 30s debounce.
    """

    enabled: bool = True
    aggressiveness: Aggressiveness = "high"
    # Minimum seconds between successive heavy-pass runs. 0 = no debounce.
    min_interval_secs: float = 0.0
    # If the conversation has fewer than this many messages, skip the
    # heavy pass entirely — there's nothing to dedup yet.
    min_message_count: int = 0
    # Hard cap on number of edits a single pass may apply. Bounds the
    # worst-case latency of microcompact even on huge conversations.
    max_edits_per_pass: int = 50


CONFIG = TimeBasedMCConfig()


def should_run_now(
    config: TimeBasedMCConfig,
    *,
    last_run_monotonic: float | None,
    now_monotonic: float,
    message_count: int,
) -> bool:
    """Return True when microcompact's heavy pass is allowed *this turn*.

    3.1 semantics: the stub microcompact is a no-op, so this predicate
    must return True (or False — it doesn't matter because no work
    happens either way). We return True so 3.3's swap-in is mechanical:
    the predicate already says "yes" by default; 3.3 wires the gating
    knobs and the predicate starts saying "no" sometimes.
    """
    if not config.enabled:
        return False
    if message_count < config.min_message_count:
        return False
    if last_run_monotonic is None:
        return True
    elapsed = now_monotonic - last_run_monotonic
    return elapsed >= config.min_interval_secs


__all__ = [
    "Aggressiveness",
    "TimeBasedMCConfig",
    "CONFIG",
    "should_run_now",
]
