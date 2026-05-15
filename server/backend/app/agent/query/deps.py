"""
Query dependency injection.

Port of src/query/deps.ts. Lets tests inject fakes for the most-mocked I/O
deps without per-module spy boilerplate.

Phase 3.1 update: ``microcompact`` and ``autocompact`` now resolve to
the real (stub-bodied) modules under ``services/compact/`` and return
the typed shapes (``MicrocompactResult`` / ``(CompactionResult, int)``)
so the query loop's pipeline wire-up doesn't shift again when Phase
3.2/3.3 swap algorithms in. The bodies are no-ops; the call shapes
are final.
"""

from __future__ import annotations

import uuid as _uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, AsyncIterator, Awaitable, Callable

if TYPE_CHECKING:
    from ..services.compact.types import (
        AutocompactReturn,
        MicrocompactResult,
    )
    from ..types.message import Message

# ── Type aliases for the dep callables ─────────────────────────────────────

# Model streaming call — yields stream events / messages, returns final message.
# Real impl wired in Phase 1.3 (services/api/claude.py → litellm_bridge).
CallModelFn = Callable[..., AsyncIterator[Any]]

# Microcompact: rule-based truncation. Now returns ``MicrocompactResult``
# (messages + optional CompactionInfo) rather than a bare message list —
# the query loop reads ``.compaction_info.pending_cache_edits`` for the
# cached variant in 3.3 and ``.messages`` for the plumb-through path.
MicrocompactFn = Callable[
    [list["Message"], Any],
    Awaitable["MicrocompactResult"],
]

# AutoCompact: LLM-driven summary. Returns ``(CompactionResult, int)`` —
# second element is the threaded ``consecutive_failures`` count. The
# query loop carries this in ``State`` across iterations and resets on
# success.
AutocompactFn = Callable[..., Awaitable["AutocompactReturn"]]

# Platform.
UuidFn = Callable[[], str]


# ── QueryDeps ──────────────────────────────────────────────────────────────


@dataclass
class QueryDeps:
    """I/O dependencies for the query loop."""

    # Model call (Phase 1.3 wires to litellm_bridge).
    callModel: CallModelFn = None  # type: ignore[assignment]
    # Compaction stages — see ``services/compact/`` for impls.
    microcompact: MicrocompactFn = None  # type: ignore[assignment]
    autocompact: AutocompactFn = None  # type: ignore[assignment]
    # Platform.
    uuid: UuidFn = field(default_factory=lambda: lambda: str(_uuid.uuid4()))


def production_deps() -> QueryDeps:
    """
    Default deps for production.

    Phase 1.3 wires `callModel` to services/api/claude.query_model_with_streaming
    (which delegates to the existing provider_bridge.resolve_provider per the
    app's billing/plans config).

    Phase 3.1 wires ``microcompact`` / ``autocompact`` to the stub modules
    in ``services/compact/`` so the call shapes are stable. Phase 3.2-3.3
    swap the bodies in without touching this file or the query loop.
    """
    # Local import to break a top-level cycle (services/api/claude imports Tool;
    # Tool imports types/hooks which doesn't import deps.py — but we keep this
    # local-import pattern as a safety habit for the loop's I/O dependencies).
    from ..services.api.claude import query_model_with_streaming
    from ..services.compact.auto_compact import autocompact
    from ..services.compact.micro_compact import microcompact

    return QueryDeps(
        callModel=query_model_with_streaming,
        microcompact=microcompact,
        autocompact=autocompact,
        uuid=lambda: str(_uuid.uuid4()),
    )
