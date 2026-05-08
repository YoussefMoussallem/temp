"""
Compaction warning hook — runs once per turn, decides whether to nudge.

Source: src/services/compact/compactWarningHook.ts (16 lines).

The hook is a thin wrapper over ``compute_warning_state``. We keep it
as its own module — even though the body is two lines — so the call
site in ``query_loop`` reads as a hook (not a primitive estimate),
matching how source's loop expresses the same concept.

Why this shape (a hook, not just a call to compute_warning_state in
the loop):

  - Future variants (e.g. throttle the warning to once-per-N-turns,
    or escalate severity at 75%/85%) live here without polluting
    the loop.
  - Tests can mock the hook to force-fire / suppress warnings without
    touching the estimator.
"""

from __future__ import annotations

from typing import Any, Sequence

from .compact_warning_state import WarningState, compute_warning_state


def compact_warning_hook(messages: Sequence[Any]) -> WarningState:
    """Compute the per-turn warning verdict.

    Pure delegating wrapper today. If/when escalation tiers, throttling,
    or per-conversation hysteresis lands, this is where they go — the
    loop and the SSE wire shape stay stable.

    Args:
      messages: pipeline-stage messages (after the 5-stage preprocessing
        but before the model call). We measure post-preprocessing so
        the warning reflects what the model will actually see.

    Returns:
      ``WarningState``; loop emits a ``compact_warning`` SSE event
      iff ``state.should_show``.
    """
    return compute_warning_state(messages)


__all__ = ["compact_warning_hook"]
