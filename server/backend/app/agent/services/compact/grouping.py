"""
Message grouping helpers — used by ``microCompact`` and ``snipCompact``
to identify clusters of related tool_use/tool_result pairs that can be
folded together.

Source: src/services/compact/grouping.ts (63 lines).

Two grouping concepts source uses:

  1. **By tool_use_id** — every tool_result references the tool_use that
     produced it via ``tool_use_id``. A "group" is the (tool_use,
     tool_result) pair. ``microcompact`` operates on these — folding a
     repeated tool_result into a preview means rewriting the *result*
     half of the pair while leaving the *use* half intact. Pair
     integrity is the cardinal rule: never rewrite one without the other.

  2. **By collapse-window** — successive Read/Search calls in a single
     assistant message form a "batch". ``apply_collapses_if_needed``
     detects these and replaces with a single ``collapsed_read_search``
     placeholder message.

Phase 3.1 ships the public surface (``find_tool_pairs``,
``find_collapse_groups``, ``find_repeated_tool_results``). The 3.1
implementations are correct for the simple cases the stubs need; 3.3
expands to handle the edge cases (tool_result without matching
tool_use after a compact boundary, nested grouped_tool_use, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class ToolPair:
    """One (tool_use, tool_result) link.

    ``use_idx`` and ``result_idx`` are positions in the *flat content
    block stream* across messages, not message indices, because a
    single assistant message can hold multiple tool_use blocks and a
    single user message can hold multiple tool_result blocks.

    ``message_use_idx`` / ``message_result_idx`` are the indices of the
    enclosing messages — needed by ``snipCompact`` for the case where
    the result is dropped but the message wrapper has to stay (other
    blocks in the same message survive).
    """
    tool_use_id: str
    use_idx: int
    result_idx: int | None
    message_use_idx: int
    message_result_idx: int | None


def _iter_blocks(messages: Iterable[Any]):
    """Walk every content block with its enclosing message index. Skips
    messages without an inner ``content`` array."""
    for m_idx, msg in enumerate(messages):
        if not isinstance(msg, Mapping):
            continue
        inner = msg.get("message")
        if not isinstance(inner, Mapping):
            continue
        content = inner.get("content")
        if not isinstance(content, list):
            continue
        for b in content:
            yield m_idx, b


def find_tool_pairs(messages: list[Any]) -> list[ToolPair]:
    """Match every tool_use to its tool_result by ``tool_use_id``.

    A tool_use without a matching tool_result is reported with
    ``result_idx=None``. The reverse — orphan tool_result — isn't
    represented here because the source convention is "results without
    a matching use are pruned by ``post_compact_cleanup`` before this
    helper sees them". 3.3 will revisit if that invariant breaks.
    """
    use_positions: dict[str, tuple[int, int]] = {}
    result_positions: dict[str, tuple[int, int]] = {}

    block_idx = 0
    for m_idx, block in _iter_blocks(messages):
        if not isinstance(block, Mapping):
            block_idx += 1
            continue
        btype = block.get("type")
        if btype == "tool_use":
            tid = block.get("id")
            if isinstance(tid, str):
                use_positions[tid] = (block_idx, m_idx)
        elif btype == "tool_result":
            tid = block.get("tool_use_id")
            if isinstance(tid, str):
                result_positions[tid] = (block_idx, m_idx)
        block_idx += 1

    pairs: list[ToolPair] = []
    for tid, (use_b, use_m) in use_positions.items():
        res = result_positions.get(tid)
        pairs.append(ToolPair(
            tool_use_id=tid,
            use_idx=use_b,
            result_idx=res[0] if res else None,
            message_use_idx=use_m,
            message_result_idx=res[1] if res else None,
        ))
    return pairs


@dataclass
class RepeatedResultGroup:
    """All tool_results bound to the same ``tool_use_id``.

    The microcompact "fold repeated tool_results" pass keeps the LAST
    occurrence in full and rewrites earlier ones to previews — that's
    why this returns the full list of indices, not just first/last.
    """
    tool_use_id: str
    occurrences: list[int] = field(default_factory=list)


def find_repeated_tool_results(messages: list[Any]) -> list[RepeatedResultGroup]:
    """Group tool_result blocks by their ``tool_use_id``.

    A normal turn has one tool_result per tool_use_id, so most groups
    are length 1 and microcompact has nothing to do. Replays + retries
    can produce duplicates; that's the case microcompact targets.
    """
    by_id: dict[str, RepeatedResultGroup] = {}
    block_idx = 0
    for _m_idx, block in _iter_blocks(messages):
        if isinstance(block, Mapping) and block.get("type") == "tool_result":
            tid = block.get("tool_use_id")
            if isinstance(tid, str):
                grp = by_id.get(tid)
                if grp is None:
                    grp = RepeatedResultGroup(tool_use_id=tid)
                    by_id[tid] = grp
                grp.occurrences.append(block_idx)
        block_idx += 1
    return [g for g in by_id.values() if len(g.occurrences) > 1]


@dataclass(frozen=True)
class CollapseGroup:
    """A run of consecutive Read/Search/List tool_uses in one assistant
    message, eligible for replacement by a ``collapsed_read_search``
    placeholder.

    Phase 3.4 ``apply_collapses_if_needed`` walks the messages, detects
    these groups via this helper, and rewrites them. The helper itself
    is content-only; the rewrite logic lives in ``context_collapse``.
    """
    message_idx: int
    block_indices: tuple[int, ...]
    tool_names: tuple[str, ...]


# Tool names that the collapse pass treats as cluster candidates. Match
# source's set; expand here when new read/search tools land. Lower-cased
# match — collapse runs against runtime tool names which are
# case-sensitive on the wire but often differ in casing across forks.
_COLLAPSIBLE_TOOLS = frozenset({
    "read", "glob", "grep", "ls", "list",
})


def find_collapse_groups(messages: list[Any]) -> list[CollapseGroup]:
    """Detect consecutive Read/Search/List tool_uses inside a single
    assistant message. Phase 3.1 returns groups for the simple pattern;
    3.4 expands to handle Memory* variants and grouping across the
    micro-batch boundaries source uses.

    Single-tool runs (``len == 1``) are *not* a collapse group; the
    minimum is 2 since collapsing one is more noise than signal.
    """
    groups: list[CollapseGroup] = []
    for m_idx, msg in enumerate(messages):
        if not isinstance(msg, Mapping):
            continue
        inner = msg.get("message")
        if not isinstance(inner, Mapping):
            continue
        if inner.get("role") != "assistant":
            continue
        content = inner.get("content")
        if not isinstance(content, list):
            continue

        run_block_idxs: list[int] = []
        run_names: list[str] = []
        for b_idx, block in enumerate(content):
            if (
                isinstance(block, Mapping)
                and block.get("type") == "tool_use"
                and (block.get("name") or "").lower() in _COLLAPSIBLE_TOOLS
            ):
                run_block_idxs.append(b_idx)
                run_names.append(str(block.get("name") or ""))
            else:
                if len(run_block_idxs) >= 2:
                    groups.append(CollapseGroup(
                        message_idx=m_idx,
                        block_indices=tuple(run_block_idxs),
                        tool_names=tuple(run_names),
                    ))
                run_block_idxs = []
                run_names = []
        if len(run_block_idxs) >= 2:
            groups.append(CollapseGroup(
                message_idx=m_idx,
                block_indices=tuple(run_block_idxs),
                tool_names=tuple(run_names),
            ))
    return groups


__all__ = [
    "ToolPair",
    "RepeatedResultGroup",
    "CollapseGroup",
    "find_tool_pairs",
    "find_repeated_tool_results",
    "find_collapse_groups",
]
