"""
Compaction-pipeline types — the structural contract between the five
preprocessing stages and the query loop.

Source: src/types/message.ts (compact-related slice) +
src/services/compact/types.ts. This module collects the shapes that
3.1 needs to lock the wire-up; algorithm details land in 3.2-3.4.

Why dataclasses (not pydantic / TypedDict):

  - These types cross internal module boundaries only; they never
    serialize to/from the API or SSE wire. Pydantic adds runtime cost
    and import-time overhead with no payoff here.
  - TypedDict is structurally compatible with the loose ``Message``
    type, but TypedDict instances can't carry default values or
    factory methods (e.g. ``CompactionResult.no_op()``) — both are
    important for the stub stages in 3.1.
  - Dataclasses match the existing style in ``query.deps`` /
    ``query.transitions`` / ``Tool.py`` — keeping convention reduces
    cognitive load on readers.

Frozen vs. mutable: kept mutable. The microcompact stage (3.3) builds
results incrementally (``info.edits_applied += 1`` style) and the
``messages`` lists are intentionally aliasable. ``CompactBoundary`` is
frozen because it's emitted onto the SSE stream and consumed by
chat-ui — treating it as immutable matches the wire contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal


# ── Boundary marker ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CompactBoundary:
    """Marker emitted into the message stream where the model's view of
    history was summarized. Survives in the transcript so chat-ui can
    render the inline "compacted" divider and the user can click to
    expand the summary.

    Source: src/types/message.ts ``SystemCompactBoundaryMessage``.

    Token counts:
      - ``tokens_before`` — estimated total of pre-boundary messages.
        Set from ``estimate_messages_tokens`` at compact time.
      - ``tokens_after`` — same metric for the kept tail + summary.
        Drives the chat-ui "saved N tokens" indicator.

    ``manual`` flag distinguishes ``/compact`` from auto-fired compaction
    so the UI can show different copy ("you ran /compact" vs "context
    was getting full"). Source uses the same flag for the same purpose.
    """
    type: Literal["compact_boundary"] = "compact_boundary"
    tokens_before: int = 0
    tokens_after: int = 0
    dropped_count: int = 0
    summary: str = ""
    manual: bool = False
    # ISO8601 string. Frozen dataclass + datetime fields don't compose
    # well; serializing to string here matches the SSE wire format.
    compacted_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# ── Per-pass info (microcompact) ───────────────────────────────────────────


@dataclass
class CompactionInfo:
    """Bookkeeping from one microcompact pass.

    Source: src/services/compact/microCompact.ts return shape.

    ``pending_cache_edits`` carries the cache_control header edits
    that ``cachedMicrocompact`` produces — the compaction logic
    decides "this tool_result should be folded to a preview" but the
    actual provider-side edit happens via cache_control on the next
    LLM call. Phase 3.3 wires this end-to-end; in 3.1 it's an empty
    list returned by the stub.

    ``edits_applied`` lets tests assert "microcompact actually did N
    things" without inspecting messages — useful when the boundary
    deferral pattern (Phase 3.3) means edits are committed but not
    yet visible in messages this turn.
    """
    tokens_freed: int = 0
    edits_applied: int = 0
    pending_cache_edits: list[Any] = field(default_factory=list)


# ── Stage results ──────────────────────────────────────────────────────────


@dataclass
class SnipResult:
    """Output of ``snip_compact_if_needed`` (Layer 2 supporting).

    Source itself ships ``snipCompact.ts`` as a 17-line stub — there's
    no production algorithm yet. We carry a real ``tokens_freed`` value
    so the autocompact threshold check (``estimate_tokens(messages) -
    snip_tokens_freed > THRESHOLD``) plumbs cleanly even when the snip
    is a no-op.

    The pipeline integration is the contract; the algorithm is TBD.
    """
    messages: list[Any]
    tokens_freed: int = 0


@dataclass
class MicrocompactResult:
    """Output of microcompact stage. Phase 3.1 stub; full impl in 3.3.

    ``compaction_info`` is None when nothing changed (cheap-path) and
    a ``CompactionInfo`` instance when at least one edit was made.
    Tests/observers branch on truthy-ness without poking internals.
    """
    messages: list[Any]
    compaction_info: CompactionInfo | None = None


@dataclass
class CollapseResult:
    """Output of ``apply_collapses_if_needed`` (Layer 2 supporting).

    Per the Phase 3.4 wire-up note, collapse runs *before* autocompact
    so a successful collapse can drop tokens below the autocompact
    threshold, skipping the expensive LLM summary. The ``collapsed_count``
    feeds analytics ("how often does collapse save us from autocompact?").
    """
    messages: list[Any]
    collapsed_count: int = 0


# ── Top-level compaction result ────────────────────────────────────────────


@dataclass
class CompactionResult:
    """Output of a full compact_conversation call (Layer 1 / autocompact).

    Source: src/services/compact/compact.ts return shape.

    ``skipped`` distinguishes "we didn't need to compact" from "we
    compacted to zero" (the latter shouldn't happen in practice but
    is structurally distinct). Used by the query loop to decide
    whether to emit a boundary onto the stream.

    ``boundary`` is what gets injected into the message stream for
    chat-ui to render. ``kept_messages`` replaces the input ``messages``
    on a successful compact. ``summary`` is the LLM's prose summary
    of the dropped messages (also embedded in ``boundary.summary``);
    duplicated here so callers can grab it without unpacking the
    nested boundary.
    """
    summary: str = ""
    boundary: CompactBoundary | None = None
    kept_messages: list[Any] = field(default_factory=list)
    dropped_count: int = 0
    tokens_before: int = 0
    tokens_after: int = 0
    # True when no compaction occurred (under threshold OR stub path).
    # ``compaction_result.skipped`` is the standard predicate the query
    # loop uses; don't replace with ``boundary is None`` because future
    # stub behavior may emit a "tracking-only" boundary.
    skipped: bool = True

    @classmethod
    def no_op(cls) -> "CompactionResult":
        """Canonical "nothing happened" result. Used by the 3.1 autocompact
        stub, by reactive_compact when threshold isn't met, and by tests
        asserting the skip path."""
        return cls(skipped=True)


# ── Tuple alias for autocompact's return shape ────────────────────────────


# autocompact returns ``(result, new_consecutive_failures)``. Aliasing the
# tuple here keeps ``query.deps.AutocompactFn`` documentable without
# leaking the implementation detail that it's a 2-tuple. Type alias is a
# Python 3.10+ ``tuple[A, B]`` literal — no PEP 695 syntax to keep
# compatibility with the project's 3.11+ floor.
AutocompactReturn = tuple[CompactionResult, int]


__all__ = [
    "CompactBoundary",
    "CompactionInfo",
    "CompactionResult",
    "CollapseResult",
    "MicrocompactResult",
    "SnipResult",
    "AutocompactReturn",
]
