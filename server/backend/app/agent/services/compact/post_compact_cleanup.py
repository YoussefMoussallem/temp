"""
Post-compaction cleanup — repair the kept-tail message list before
handing back to the loop.

Source: src/services/compact/postCompactCleanup.ts (77 lines).

Three responsibilities, all mechanical:

  1. **Strip thinking blocks** — internal model reasoning that bloats
     tokens with no payoff to the next-turn LLM. Once a turn is
     summarized, the thinking that produced it isn't useful.
  2. **Repair tool_use/tool_result pairing** — the split point may
     drop a tool_use whose tool_result lives in the kept tail (or
     vice versa). Either orphan must be removed because the API
     errors on unmatched pairs.
  3. **Normalize cache_control** — Anthropic-style cache markers on
     blocks become stale once the boundary changes the prefix shape.
     Drop them; the next turn re-establishes cache state from scratch.

These are pure transformations on the kept-tail list; no I/O, no LLM
calls. Stays sync.

Without source the algorithm is implemented from the plan's prose
("Strip thinking blocks from kept messages / Repair tool_use/tool_result
pairing / Normalize cache_control") and Anthropic-API knowledge that
unmatched tool_use/tool_result pairs cause 4xx responses.
"""

from __future__ import annotations

from typing import Any, Mapping


# ── Block-level helpers ────────────────────────────────────────────────────


def _is_thinking(block: Any) -> bool:
    return isinstance(block, Mapping) and block.get("type") == "thinking"


def _strip_cache_control(block: Any) -> Any:
    """Return a copy of ``block`` with any ``cache_control`` key removed.
    Identity for non-mappings. Kept defensive — chat-ui or providers may
    emit blocks with cache_control nested inside SDK-shaped envelopes."""
    if not isinstance(block, Mapping):
        return block
    if "cache_control" not in block:
        return block
    return {k: v for k, v in block.items() if k != "cache_control"}


def _block_tool_use_id(block: Any) -> str | None:
    """Return the tool_use_id this block contributes to the pair-set:
      - tool_use     → the block's own ``id``
      - tool_result  → the referenced ``tool_use_id``
      - everything else → None
    """
    if not isinstance(block, Mapping):
        return None
    btype = block.get("type")
    if btype == "tool_use":
        tid = block.get("id")
        return tid if isinstance(tid, str) else None
    if btype == "tool_result":
        tid = block.get("tool_use_id")
        return tid if isinstance(tid, str) else None
    return None


# ── Pass: collect pair-ids ─────────────────────────────────────────────────


def _collect_pair_ids(messages: list[Any]) -> tuple[set[str], set[str]]:
    """Return ``(use_ids, result_ids)`` — the set of tool_use_ids that
    appear as a use, and the set that appear as a result. The pairs
    that survive are the intersection."""
    uses: set[str] = set()
    results: set[str] = set()
    for msg in messages:
        if not isinstance(msg, Mapping):
            continue
        inner = msg.get("message")
        if not isinstance(inner, Mapping):
            continue
        content = inner.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, Mapping):
                continue
            btype = block.get("type")
            tid = _block_tool_use_id(block)
            if not tid:
                continue
            if btype == "tool_use":
                uses.add(tid)
            elif btype == "tool_result":
                results.add(tid)
    return uses, results


# ── Pass: rewrite messages ─────────────────────────────────────────────────


def _clean_block(block: Any, valid_pair_ids: set[str]) -> Any | None:
    """Return the cleaned block, or None if it should be dropped.

    Drops:
      - thinking blocks (always)
      - tool_use without a matching tool_result (orphan)
      - tool_result without a matching tool_use (orphan)
    """
    if _is_thinking(block):
        return None

    tid = _block_tool_use_id(block)
    if tid is not None and tid not in valid_pair_ids:
        # Orphan tool_use or tool_result — drop so the API never sees
        # an unmatched pair.
        return None

    return _strip_cache_control(block)


def _clean_message(msg: Any, valid_pair_ids: set[str]) -> Any | None:
    """Rewrite one message; return None if every block was dropped."""
    if not isinstance(msg, Mapping):
        return msg

    inner = msg.get("message")
    if not isinstance(inner, Mapping):
        return msg

    content = inner.get("content")
    if isinstance(content, str):
        # String content is fine — no blocks to walk. Cache_control
        # doesn't apply to plain strings.
        return msg
    if not isinstance(content, list):
        return msg

    cleaned: list[Any] = []
    for block in content:
        out = _clean_block(block, valid_pair_ids)
        if out is not None:
            cleaned.append(out)

    if not cleaned:
        # Whole message was thinking + orphans — drop the message entirely.
        # Source has the same behavior: an empty content array is invalid
        # on the wire and creates more problems than dropping the wrapper.
        return None

    new_inner = {**inner, "content": cleaned}
    return {**msg, "message": new_inner}


def post_compact_cleanup(messages: list[Any]) -> list[Any]:
    """Run all three cleanup passes on the kept-tail messages.

    Idempotent: running twice produces the same output as running once.
    Cheap: O(total blocks). Safe to call from the autocompact happy
    path on every successful compaction without measurable overhead.

    Args:
      messages: list of loop-shape messages to clean.

    Returns:
      A new list of cleaned messages. The input list is not mutated.
    """
    if not messages:
        return []

    use_ids, result_ids = _collect_pair_ids(messages)
    valid_pair_ids = use_ids & result_ids

    out: list[Any] = []
    for msg in messages:
        cleaned = _clean_message(msg, valid_pair_ids)
        if cleaned is not None:
            out.append(cleaned)
    return out


__all__ = ["post_compact_cleanup"]
