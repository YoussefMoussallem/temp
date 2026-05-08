"""
Snip projection — selects which fields of a tool_result block are kept
when ``snipCompact`` decides to fold it.

Source: src/services/compact/snipProjection.ts (7 lines).

Phase 3.1 ships the import surface; Phase 3.4 supplies the algorithm
when ``snipCompact`` itself becomes more than a stub. The 7-line source
shape is preserved so a future port slots in cleanly without callers
needing to refactor.

Keep this file *small*. The whole point of having ``snip_projection``
as its own module rather than a private function inside ``snip_compact``
is to mirror source's file boundary so a parity-port grep over the
plan stays mechanical. Don't grow it.
"""

from __future__ import annotations

from typing import Any


def project_for_snip(block: Any) -> Any:
    """Identity in 3.1. Real impl (3.4) returns the snipped projection of
    the block — typically: keep ``tool_use_id``, replace ``content`` with
    a one-line preview, drop everything else.

    Returning the input unchanged is the safe stub: callers that pipe a
    block through this helper will see no behavior change until the real
    projection lands.
    """
    # TODO(3.4): real projection per src/services/compact/snipProjection.ts.
    return block
