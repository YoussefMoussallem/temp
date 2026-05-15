"""Fork-subagent gate — stub.

Source ``tools/AgentTool/forkSubagent.ts`` exposes a feature flag that
turns on the "fork from current context" path (subagent_type omitted →
fork the parent's full message context). Edwin v1 keeps this off; the
flag exists so AgentTool.call() can branch defensively even though the
implementation is deferred.
"""

from __future__ import annotations


def is_fork_subagent_enabled() -> bool:
    """Always False in v1 — fork dispatch is deferred."""
    return False
