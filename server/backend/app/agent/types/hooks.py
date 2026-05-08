"""
Hook callback types.

Minimal port of src/types/hooks.ts. Full hook engine (PromptSubmit, PreToolUse,
PostToolUse, Stop) lands in Phase 4 (per project_agent_port_hooks). For now,
this file exposes only the types Tool.py needs:

- CanUseToolFn — the permission gate callable type
- PromptRequest / PromptResponse — UI prompt elicitation protocol
- HookProgress — progress event for hook execution

Larger v1 surface (sync/async hook response schemas, hook-specific output
unions for PreToolUse/UserPromptSubmit) will be added in Phase 4.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Literal

if TYPE_CHECKING:
    from .permissions import PermissionResult


# ============================================================================
# Permission Gate
# ============================================================================

# CanUseToolFn — passed into Tool.call(); allows the tool to re-check
# permissions mid-execution (e.g., per-line-range file access).
CanUseToolFn = Callable[
    [str, dict[str, Any]],  # (toolName, input)
    Awaitable["PermissionResult"],
]


# ============================================================================
# Prompt Elicitation Protocol
# ============================================================================


@dataclass
class PromptRequestOption:
    key: str
    label: str
    description: str | None = None


@dataclass
class PromptRequest:
    prompt: str  # request id
    message: str
    options: list[PromptRequestOption]


@dataclass
class PromptResponse:
    prompt_response: str  # request id
    selected: str


# ============================================================================
# Hook Progress
# ============================================================================


@dataclass
class HookProgress:
    type: Literal["hook_progress"] = "hook_progress"
    hookName: str = ""
    message: str = ""
