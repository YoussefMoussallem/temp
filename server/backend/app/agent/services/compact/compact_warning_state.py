"""
Compaction warning state — context-fill bookkeeping.

Source: src/services/compact/compactWarningState.ts (18 lines).

The reference impl keeps a *process-level* singleton because the source
CLI is one long-running process per user — that singleton holds
``should_show_warning`` and ``last_warning_at`` across turns. Edwin's
backend is stateless (per the architecture-phase3 rule) so a process-
singleton would either be (a) shared across users, which is wrong, or
(b) effectively recomputed every turn anyway because there's no
authoritative per-user place to put it.

We pick (b) explicitly: ``WarningState`` is a *value type*, not a
singleton. Every turn computes it fresh from the current message list.
The frontend handles dismissal (it's UX state — "the user clicked X").

What the backend ships:
  - ``WarningState`` dataclass (the wire shape)
  - ``compute_warning_state`` helper (pure function: messages → state)

Constants:
  - ``WARNING_THRESHOLD_PCT = 0.70`` — context-fill at which we start
    nudging. Source uses the same percentage; the autocompact firing
    point is 80%, so 70% gives the user a one-step heads-up.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from app_logger import get_logger

from app.config import get_settings

from ..token_estimation import estimate_messages_tokens
from .auto_compact import AUTO_COMPACT_THRESHOLD_TOKENS

log = get_logger(__name__)


# ── Threshold ──────────────────────────────────────────────────────────────


# 70% of the assumed context window. Computed once from
# ``AUTO_COMPACT_THRESHOLD_TOKENS`` (which is 80% of context) so they stay
# in lock-step: bumping autocompact's threshold automatically bumps the
# warning threshold.
WARNING_THRESHOLD_PCT = 0.70

# 80% of context = AUTO_COMPACT_THRESHOLD_TOKENS, so 70% = that × 70/80.
_DEFAULT_WARNING_THRESHOLD_TOKENS = int(AUTO_COMPACT_THRESHOLD_TOKENS * 70 / 80)

# Env override: ``EDWIN_WARNING_THRESHOLD_TOKENS`` in ``backend/.env``
# (loaded via ``app.config``). ``0`` falls back to 70% of the
# autocompact threshold (which itself may be overridden), keeping the
# two thresholds linked unless the user explicitly decouples them.
_override = get_settings().compaction.warning_threshold_tokens
WARNING_THRESHOLD_TOKENS = _override if _override > 0 else _DEFAULT_WARNING_THRESHOLD_TOKENS
if _override > 0:
    log.warning(
        "warning threshold overridden via EDWIN_WARNING_THRESHOLD_TOKENS: %d (default %d)",
        _override,
        _DEFAULT_WARNING_THRESHOLD_TOKENS,
    )


# ── State value ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class WarningState:
    """Wire-shape for a compact_warning SSE event payload.

    All fields are integer/float to keep the JSON encoding cheap and the
    frontend rendering deterministic. ``fill_pct`` is computed against
    the *autocompact* threshold (the 100% mark) so the UI's progress
    bar lines up with the autocompact firing point — not the warning
    threshold.

    ``should_show`` is the hook's verdict; the frontend can subscribe
    just to it and ignore the diagnostics if it wants. Keeping the
    diagnostics on the wire lets future telemetry land without a
    schema bump.
    """

    should_show: bool
    current_tokens: int
    autocompact_threshold_tokens: int
    warning_threshold_tokens: int
    fill_pct: float


# ── Pure helper ────────────────────────────────────────────────────────────


def compute_warning_state(messages: Sequence[Any]) -> WarningState:
    """Compute warning state from the current message list.

    Pure: no I/O, no global mutation, no async. Cheap to call every
    turn — token estimation is O(total content chars).

    Args:
      messages: pipeline-stage messages (post-preprocessing in the
        loop). Token estimate uses the same shape and helpers as
        ``autocompact``'s threshold check, so the two stay in sync.

    Returns:
      ``WarningState`` with ``should_show=True`` iff the estimated
      total exceeds ``WARNING_THRESHOLD_TOKENS``.
    """
    current = estimate_messages_tokens(messages)
    fill_pct = current / AUTO_COMPACT_THRESHOLD_TOKENS if AUTO_COMPACT_THRESHOLD_TOKENS > 0 else 0.0
    return WarningState(
        should_show=current >= WARNING_THRESHOLD_TOKENS,
        current_tokens=current,
        autocompact_threshold_tokens=AUTO_COMPACT_THRESHOLD_TOKENS,
        warning_threshold_tokens=WARNING_THRESHOLD_TOKENS,
        fill_pct=fill_pct,
    )


__all__ = [
    "WARNING_THRESHOLD_PCT",
    "WARNING_THRESHOLD_TOKENS",
    "WarningState",
    "compute_warning_state",
]
