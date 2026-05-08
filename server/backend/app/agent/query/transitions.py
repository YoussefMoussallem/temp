"""
Loop transition types.

Port of src/query/transitions.ts. The TS source is itself an auto-generated
stub (`Terminal = any; Continue = any;`). This Python port gives them concrete
shapes that the loop actually returns/sets so callers can branch on them.

The loop's State.transition records the REASON the previous iteration continued
— useful for tests asserting recovery paths fired without inspecting message
contents.

Source documents 7 termination paths and 4 continuation paths. v1 implements
the simple subset (completed / model_error / aborted_streaming) and stubs the
recovery paths (max_output_tokens recovery, prompt_too_long recovery, stop hook
blocking) for Phase 3.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# Reasons the loop terminated (returned).
TerminalReason = Literal[
    "completed",          # No tool_use + stop hooks pass → return
    "blocking_limit",     # Token count exceeds hard limit (PTL)
    "aborted_streaming",  # User ESC during streaming
    "model_error",        # API throws exception
    "prompt_too_long",    # Reactive compact failed; PTL released
    "image_error",        # Image size/type error
    "stop_hook_prevented",# Hook injects preventContinuation:true
    "max_turns",          # maxTurns guard exceeded
]


@dataclass(frozen=True)
class Terminal:
    """Loop terminated; returned to caller."""
    reason: TerminalReason
    detail: str | None = None


# Reasons the loop continued (next iteration).
ContinueReason = Literal[
    "tool_cycle",                 # Normal: tools executed, continue
    "max_output_tokens_recovery", # Escalate to 64K, retry
    "context_collapse_drain",     # Commit staged collapses, retry
    "reactive_compact",           # On-the-fly compression, retry
    "stop_hook_blocking_retry",   # Hook blocked; append error, retry
]


@dataclass(frozen=True)
class Continue:
    """Loop continued to next iteration; recorded on State.transition."""
    reason: ContinueReason
    detail: str | None = None
