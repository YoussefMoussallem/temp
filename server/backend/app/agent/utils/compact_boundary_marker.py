"""
Compact-boundary persistence — the on-disk shape of a compaction event.

This module is the single source of truth for how compaction boundaries
are persisted to the ``messages`` table and how they are interpreted
when loading conversation history for the LLM.

Why a typed marker message (and not a schema column)
----------------------------------------------------
Edwin's architecture rule keeps ``messages`` strictly append-only and
``conversations`` mostly so. We chose to model a compaction boundary
as a regular row with::

    role     = "system"  (already permitted by the messages.role CHECK)
    content  = [{"type": "compact_boundary", ...}]   (JSONB)

This means:

  * **Zero schema change.** No alembic migration; no FK juggling.
  * **Audit trail preserved.** Every compaction event lives in the
    table forever. ``/clear`` truncates them along with everything
    else, which is the right semantics.
  * **History is reconstructable.** The full pre-boundary conversation
    is still queryable for ops/dev or a future "restore" command.
  * **Multiple boundaries work.** A long-lived conversation can carry
    many compaction events; the *latest* one wins for the LLM view,
    and the UI can render every one as a divider.

What this module exposes
------------------------
  * ``BOUNDARY_TYPE`` — the string we look for in ``content[0].type``.
  * ``make_boundary_payload`` — turn a runtime ``CompactBoundary`` into
    the JSONB-shaped list we hand to ``db_client.append_message``.
  * ``is_boundary_row`` — strict predicate for "is this row a boundary
    marker?". Defensive — checks role, content shape, and the type tag.
  * ``find_latest_boundary_index`` — returns the *index* of the latest
    boundary row in a list of db rows, or ``None`` if none exist.
  * ``apply_boundary_filter`` — the LLM-facing filter. Drops every row
    strictly before the latest boundary, swaps the boundary row itself
    for a synthesized ``user``-shape message containing the summary
    text, and keeps every post-boundary row verbatim.

Wire-up points
--------------
  * ``agent/router.py::_build_turn_messages`` — calls
    ``apply_boundary_filter`` after loading history so the agent loop
    sees the compacted view.
  * ``agent/router.py::_stream_turn`` — when the loop yields a
    ``compact_boundary`` event, the router uses
    ``make_boundary_payload`` and persists via
    ``_append_with_retry(role="system", content=payload)``.
  * ``agent/commands/compact/compact.py`` — same payload shape, same
    persistence call.

Invariants
----------
  * The persisted boundary row's content is *always* a single-element
    list with ``type == BOUNDARY_TYPE``. If a future change adds more
    blocks, ``is_boundary_row`` and the filter must be updated together.
  * Synthesizing the summary as a ``user``-role message (not
    ``system``) matches what ``compact_conversation`` already produces
    in-memory mid-turn: keeping the wire shape stable means the LLM
    sees the same prefix whether it's reading from a fresh in-memory
    compaction or a previously persisted one.
"""

from __future__ import annotations

from ..services.compact.types import CompactBoundary

# String constant matching ``CompactBoundary.type`` in
# ``services/compact/types.py``. Duplicated here (rather than imported
# from the dataclass field default) so this module can be used by code
# paths that haven't otherwise touched the compact subsystem.
BOUNDARY_TYPE = "compact_boundary"


def make_boundary_payload(boundary: CompactBoundary) -> list[dict]:
    """Serialize a runtime ``CompactBoundary`` to the JSONB list we
    hand to ``db_client.append_message`` as ``content``.

    The shape is the same one the SSE event carries — that lets the
    frontend's ``streamHandler`` and the DB-load path share one
    rendering code path (the existing ``CompactBoundary.jsx`` divider).

    Args:
      boundary: the runtime marker emitted by ``compact_conversation``.

    Returns:
      A single-element list of dicts; ``content`` for the new row.
    """
    return [
        {
            "type": BOUNDARY_TYPE,
            "summary": boundary.summary,
            "tokens_before": boundary.tokens_before,
            "tokens_after": boundary.tokens_after,
            "dropped_count": boundary.dropped_count,
            "manual": boundary.manual,
            "compacted_at": boundary.compacted_at,
        }
    ]


def is_boundary_row(row: dict) -> bool:
    """Strict predicate: is ``row`` a persisted compaction boundary?

    Defensive against bad rows: requires role == 'system', content to
    be a non-empty list, the first block to be a dict with the right
    type tag. Anything else returns False so the filter is a no-op for
    legacy / malformed rows.
    """
    if row.get("role") != "system":
        return False
    content = row.get("content")
    if not isinstance(content, list) or not content:
        return False
    head = content[0]
    if not isinstance(head, dict):
        return False
    return head.get("type") == BOUNDARY_TYPE


def find_latest_boundary_index(rows: list[dict]) -> int | None:
    """Return the index of the latest (highest-sequence) boundary row,
    or ``None`` if no boundary marker exists in ``rows``.

    Walks backwards because boundaries are rare and the latest one is
    typically near the end. Caller is expected to pass rows in
    ascending-sequence order (which is what ``db_client.get_messages``
    returns).
    """
    for i in range(len(rows) - 1, -1, -1):
        if is_boundary_row(rows[i]):
            return i
    return None


def _synthesize_summary_message(boundary_row: dict) -> dict:
    """Turn a persisted boundary row into the user-shape message the
    LLM should see in place of the dropped pre-boundary history.

    Output matches the shape ``compact_conversation`` produces
    in-memory mid-turn: a ``user``-role row whose content is a single
    text block carrying the summary string. Wrapping the summary in a
    user-role message means the model treats it as factual prior
    context (not a system instruction it could try to override).
    """
    head = boundary_row["content"][0]
    summary = head.get("summary", "") or ""
    # Even when summary is empty (degenerate compaction), we still
    # produce a placeholder so the structural invariant
    # "post-boundary view starts with a single summary message" holds
    # for downstream consumers.
    text = (
        summary
        if summary
        else "(Earlier conversation summarised; no usable summary text was produced.)"
    )
    return {
        "role": "user",
        "content": [{"type": "text", "text": text}],
    }


def apply_boundary_filter(rows: list[dict]) -> list[dict]:
    """Reduce a full conversation history to the LLM-facing view.

    Behaviour:
      * No boundary present → return ``rows`` unchanged (cheap path).
      * Boundary at index ``i`` → return
        ``[<synthesised summary>, *rows[i+1:]]``.

    Notes:
      * The synthesised summary message replaces the boundary row
        itself in addition to dropping pre-boundary rows. The boundary
        marker is metadata; the model sees the summary text instead.
      * Multiple boundaries: only the latest one matters for the LLM
        view. Older boundaries (which sit pre-latest) are dropped
        along with everything else before the latest cut.
      * Caller-side audit/UI views should NOT use this filter — load
        the raw rows from db and render them with the
        ``CompactBoundary`` divider component for visual continuity.

    Args:
      rows: db-service message rows in ascending-sequence order.

    Returns:
      A new list (input not mutated). Same dict identity for kept rows;
      only the synthesised summary is freshly allocated.
    """
    idx = find_latest_boundary_index(rows)
    if idx is None:
        return list(rows)
    summary_msg = _synthesize_summary_message(rows[idx])
    return [summary_msg, *rows[idx + 1 :]]


__all__ = [
    "BOUNDARY_TYPE",
    "make_boundary_payload",
    "is_boundary_row",
    "find_latest_boundary_index",
    "apply_boundary_filter",
]
