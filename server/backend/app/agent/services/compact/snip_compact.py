"""
``snipCompact`` — pre-flight tool_result snipping (Layer 2 supporting).

Source: src/services/compact/snipCompact.ts (17 lines — itself a stub
in source).

The stage exists in the pipeline so the ``tokens_freed`` figure can
be plumbed through to the autocompact threshold check
(``estimate_tokens(messages) - snip_tokens_freed > THRESHOLD``):
that threading must be wired in 3.1 even though no actual snipping
happens yet.

Real algorithm (TBD) would project oversized tool_results down to a
preview and an on-disk pointer (see ``utils.tool_result_storage`` for
the analog). Source itself hasn't shipped that algorithm; we keep
parity by leaving this as a documented stub.
"""

from __future__ import annotations

from typing import Any

from .types import SnipResult


def snip_compact_if_needed(messages: list[Any]) -> SnipResult:
    """Phase 3.1 stub. Returns input unchanged with ``tokens_freed=0``.

    The function is sync (not async) — source's signature is sync, the
    snip operation is pure CPU on already-loaded message blobs. Keep
    sync until/unless the real impl needs filesystem I/O for storing
    snipped content (then it becomes async).

    # TODO(post-Phase-5): real snip impl per src/services/compact/snipCompact.ts
    # — project oversized tool_results to (preview, disk-pointer) tuple
    # and emit ``tokens_freed`` reflecting actual reduction.
    """
    return SnipResult(messages=messages, tokens_freed=0)


__all__ = ["snip_compact_if_needed"]
