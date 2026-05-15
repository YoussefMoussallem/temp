"""
Token estimation — cheap heuristic used by every compaction stage.

Source: src/services/tokenEstimation.ts.

Edwin doesn't ship a tokenizer dependency (no tiktoken / no provider-
specific tokenizer). The compaction pipeline only needs estimates that
are correct to within ~10-15% to make threshold decisions; the
``chars / 4`` heuristic hits that bar for English prose and is good
enough for code/JSON because tool_result blocks dominate token cost
and they're mostly text.

Why a *services*-level estimator rather than reusing
``agent.skills.token_estimate.estimate_chars_tokens``:

  - The skills helper is a private utility scoped to inventory
    rendering (a one-shot decision at boot/per-turn). The compaction
    pipeline calls these estimators on every turn, on every message,
    in inner loops — keeping the function colocated with its callers
    in ``services.compact`` avoids a cross-package dep that would
    make the skills helper accidentally part of the compaction API
    surface.
  - Different correction factor: messages have structural overhead
    (role markers, content-block envelopes, tool_use_id, etc.) the
    skills helper doesn't account for. Counting only content text
    would systematically under-estimate. We add per-block overhead
    here.
  - Memoization shape differs: skills hashes by skill identity (small
    fixed set); compaction hashes by message uuid + content-len (large
    varying set). Same code can't serve both well.

Phase 3.1 ships the estimator. Phase 3.2-3.4 callers actually exercise
it. If/when an exact tokenizer becomes available (e.g. provider returns
``usage.input_tokens`` reliably and we can backfill via a deferred
boundary message — see the Phase 3.3 "boundary deferral" pattern), we
keep this estimator as the *predictive* path and use API-reported
counts for *retrospective* boundary annotations.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Mapping, Sequence

# ── Heuristic constants ────────────────────────────────────────────────────

# Chars-per-token approximation. Calibrated against cl100k_base on English
# prose: actual ratio ~3.8-4.2; we use 4 (slight over-estimate is safer
# than under-estimate for threshold decisions — over-estimating triggers
# compaction a hair early, under-estimating risks a context-overflow API
# error mid-turn).
_CHARS_PER_TOKEN = 4

# Per-content-block structural overhead (role markers, content-block
# envelopes, tool_use_id strings, JSON braces). Empirically ~10 tokens
# per block for tool_use/tool_result envelopes on Anthropic's API.
_BLOCK_OVERHEAD_TOKENS = 10

# Per-message overhead on top of block overhead — the wrapping ``message``
# dict, ``role`` field, ``id`` field, etc. Tiny but adds up across long
# conversations.
_MESSAGE_OVERHEAD_TOKENS = 4


# ── Public API ─────────────────────────────────────────────────────────────


def estimate_tokens(text: str | None) -> int:
    """``len(text) / 4`` rounded up. Treats None and empty as 0.

    Hot path: called once per content-block string. ``lru_cache`` would
    blow up on long unique strings; callers that need memoization over
    repeated identical bodies use ``estimate_message_tokens`` which
    keys by message uuid.
    """
    if not text:
        return 0
    return (len(text) + _CHARS_PER_TOKEN - 1) // _CHARS_PER_TOKEN


def _estimate_block_tokens(block: Any) -> int:
    """One content block (text / tool_use / tool_result / image / thinking)."""
    if not isinstance(block, Mapping):
        return estimate_tokens(str(block)) + _BLOCK_OVERHEAD_TOKENS

    btype = block.get("type")
    overhead = _BLOCK_OVERHEAD_TOKENS

    if btype == "text":
        return estimate_tokens(block.get("text")) + overhead

    if btype == "tool_use":
        # name + serialized input. Input is usually small JSON; stringify
        # blindly rather than doing a recursive walk.
        name = block.get("name") or ""
        input_str = str(block.get("input") or "")
        return estimate_tokens(name) + estimate_tokens(input_str) + overhead

    if btype == "tool_result":
        # Content can be a string or a list of nested blocks (Anthropic's
        # multimodal tool_result shape). Recurse into list, cheap-path
        # the string case.
        content = block.get("content")
        if isinstance(content, str):
            return estimate_tokens(content) + overhead
        if isinstance(content, list):
            return sum(_estimate_block_tokens(b) for b in content) + overhead
        return overhead

    if btype == "thinking":
        return estimate_tokens(block.get("thinking")) + overhead

    if btype == "image":
        # Anthropic charges ~1.6 tokens per image-tile; without dimensions
        # we assume the API average (~1568 tokens for a max-sized image).
        # If/when block carries dimensions, refine here.
        return 1568 + overhead

    # Unknown block type — fall back to a stringified estimate.
    return estimate_tokens(str(block)) + overhead


def estimate_message_tokens(message: Any) -> int:
    """One message (assistant / user / system / progress)."""
    if not isinstance(message, Mapping):
        return estimate_tokens(str(message)) + _MESSAGE_OVERHEAD_TOKENS

    inner = message.get("message")
    if not isinstance(inner, Mapping):
        # Some message variants (CompactBoundary, attachment) carry
        # their payload at the top level rather than nested. Stringify
        # the whole shape — over-counts slightly, never under-counts.
        return estimate_tokens(str(message)) + _MESSAGE_OVERHEAD_TOKENS

    content = inner.get("content")
    if isinstance(content, str):
        body = estimate_tokens(content)
    elif isinstance(content, Sequence):
        body = sum(_estimate_block_tokens(b) for b in content)
    else:
        body = 0

    return body + _MESSAGE_OVERHEAD_TOKENS


def estimate_messages_tokens(messages: Sequence[Any]) -> int:
    """Sum across a message list. Cheap O(n) — no caching at this level
    because the threshold check that calls it runs once per turn."""
    if not messages:
        return 0
    return sum(estimate_message_tokens(m) for m in messages)


# ── Memoized variant for hot inner-loop callers ────────────────────────────


@lru_cache(maxsize=4096)
def _estimate_text_cached(s: str) -> int:
    """Memoized text estimator. Used by stages that re-estimate the same
    long bodies repeatedly (cachedMicrocompact's stability check). Bounded
    cache size — long-running session won't unbounded-grow."""
    return estimate_tokens(s)


def estimate_tokens_cached(text: str | None) -> int:
    """Public wrapper; cleans the None case before keying the cache."""
    if not text:
        return 0
    return _estimate_text_cached(text)
