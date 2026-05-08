"""
Tool interface — backend half.

mixes call/permission/schema concerns with
React rendering methods (renderToolUseMessage, renderToolResultMessage, etc.).
This Python port keeps ONLY the call/permission/schema half — rendering belongs
to app/ client per the placement decisions (project_agent_port_placements).

Tools are defined as Pydantic-modeled inputs + an async call() implementation.
The buildTool() factory fills in defaults — same pattern as src/Tool.ts.
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Generic, Protocol, TypeVar
from pydantic import BaseModel

from .types.hooks import CanUseToolFn
from .types.permissions import (
    PermissionAllowDecision,
    PermissionResult,
    ToolPermissionContext,
)
from .types.tools import ToolProgressData

if TYPE_CHECKING:
    from .types.message import AssistantMessage, Message


# ============================================================================
# Generics
# ============================================================================

InputT = TypeVar("InputT", bound=BaseModel)
OutputT = TypeVar("OutputT")


# ============================================================================
# Validation & Result Shapes
# ============================================================================


@dataclass(frozen=True)
class ValidationOk:
    result: bool = True


@dataclass(frozen=True)
class ValidationError:
    message: str
    errorCode: int
    result: bool = False


ValidationResult = ValidationOk | ValidationError


@dataclass
class ToolResult(Generic[OutputT]):
    """Successful tool result. Backend half — no React UI."""
    data: OutputT
    # Optional new messages to inject into the conversation post-tool.
    newMessages: list["Message"] | None = None
    # contextModifier honored only for tools that aren't concurrency safe.
    contextModifier: Callable[["ToolUseContext"], "ToolUseContext"] | None = None
    # MCP protocol metadata to pass through to SDK consumers.
    mcpMeta: dict[str, Any] | None = None
    # Extra loop events to forward to the client after this tool returns.
    # Each is a dict with at least a "type" key; the agent router's catch-all
    # SSE forwarder passes unknown event types through as-is.
    events: list[dict[str, Any]] | None = None


@dataclass
class ToolProgress(Generic[OutputT]):
    """A progress event emitted during tool execution."""
    toolUseID: str
    data: ToolProgressData


ToolCallProgress = Callable[[ToolProgress], None]


# ============================================================================
# Tool Use Context
# ============================================================================


@dataclass
class ToolUseContextOptions:
    """Options bag inside ToolUseContext. Mirrors `ToolUseContext.options`."""
    mainLoopModel: str = ""
    searchModel: str = ""
    permissionMode: str = "default"
    thinking: bool = False
    debug: bool = False
    verbose: bool = False
    isNonInteractiveSession: bool = False
    customSystemPrompt: str | None = None
    appendSystemPrompt: str | None = None
    maxBudgetUsd: float | None = None
    # Subset for v1; expanded as features land:
    # commands, tools, thinkingConfig, mcpClients, mcpResources,
    # agentDefinitions, querySource, refreshTools — Phase 1.2+.


@dataclass
class ToolUseContext:
    """
    Per-turn context handed to every tool call.

    Source has 40+ fields covering subagent forks, swarm coordinator,
    interactive REPL, Ink renderers, and more. v1 keeps the minimal
    subset that Phase 1 tools actually need; the rest are added as the
    relevant features come online (see project_agent_port_multi_agent
    for what's deferred).
    """
    options: ToolUseContextOptions = field(default_factory=ToolUseContextOptions)
    messages: list["Message"] = field(default_factory=list)
    # Per-tool input limits (v1: file reading + glob).
    fileReadingLimits: dict[str, int] | None = None
    globLimits: dict[str, int] | None = None
    # Tool use ID being processed (set when context is per-tool-call scoped).
    toolUseId: str | None = None
    # Request-scoped bindings set by the agent router. Tools that need to
    # reach db-service use `authorization` verbatim; project-scoped tools
    # (e.g. slide CRUD) use `project_id` to pick their target.
    # `conversation_id` is used by commands that mutate or read the active
    # conversation's message history (e.g. /clear, /context).
    authorization: str | None = None
    project_id: str | None = None
    conversation_id: str | None = None
    # Deferred fields (Q6 multi-agent, Q9 hooks, plan mode, subagents):
    # agentId, agentType, queryTracking, contentReplacementState,
    # renderedSystemPrompt, requireCanUseTool, requestPrompt,
    # localDenialTracking, abortController, getAppState/setAppState,
    # readFileState, etc. — added in Phase 1.2+ as needed.


# ============================================================================
# Tool Interface
# ============================================================================


class Tool(Protocol[InputT, OutputT]):
    """
    Tool interface — backend half.

    Concrete tools subclass this Protocol-style interface. See buildTool()
    for the standard construction pattern with default-method fill-in.

    Methods marked Optional in TS are typed here as default-implemented or
    explicitly Optional via __optional__ pattern (kept simple in v1).
    """

    name: str
    inputSchema: type[BaseModel]
    maxResultSizeChars: int

    # Optional: tool name aliases for backwards compatibility.
    aliases: list[str] | None
    # Optional: one-line capability hint for ToolSearch.
    searchHint: str | None
    # Optional: defer this tool's full schema (requires ToolSearch to call).
    shouldDefer: bool
    # Optional: never defer (always include full schema in initial prompt).
    alwaysLoad: bool
    # Optional: strict mode for the API.
    strict: bool
    # Optional: MCP source metadata.
    mcpInfo: dict[str, str] | None
    isMcp: bool
    isLsp: bool

    # ── Capability flags ────────────────────────────────────────────────────

    def is_enabled(self) -> bool: ...

    def is_concurrency_safe(self, input: Any) -> bool: ...

    def is_read_only(self, input: Any) -> bool: ...

    def is_destructive(self, input: Any) -> bool: ...

    def is_open_world(self, input: Any) -> bool: ...

    def requires_user_interaction(self) -> bool: ...

    def interrupt_behavior(self) -> Literal["cancel", "block"]: ...  # type: ignore[name-defined]

    # ── Permission & validation ─────────────────────────────────────────────

    async def validate_input(
        self, input: Any, context: ToolUseContext
    ) -> ValidationResult: ...

    async def check_permissions(
        self, input: Any, context: ToolUseContext
    ) -> PermissionResult: ...

    async def prepare_permission_matcher(
        self, input: Any
    ) -> Callable[[str], bool]: ...

    # ── Path helper (file-touching tools) ───────────────────────────────────

    def get_path(self, input: Any) -> str | None: ...

    # ── Schema introspection ────────────────────────────────────────────────

    def input_json_schema(self) -> dict[str, Any] | None: ...

    def output_schema(self) -> type[BaseModel] | None: ...

    # ── Comparison ──────────────────────────────────────────────────────────

    def inputs_equivalent(self, a: Any, b: Any) -> bool: ...

    # ── Description & prompt ────────────────────────────────────────────────

    async def description(
        self, input: Any, options: dict[str, Any]
    ) -> str: ...

    async def prompt(self, options: dict[str, Any]) -> str: ...

    def user_facing_name(self, input: Any) -> str: ...

    # ── Result mapping (backend → API tool_result block) ────────────────────

    def map_tool_result_to_block(
        self, content: OutputT, tool_use_id: str
    ) -> dict[str, Any]: ...

    # ── Auto-mode classifier feed ───────────────────────────────────────────

    def to_auto_classifier_input(self, input: Any) -> Any: ...

    # ── Search/read collapse hint (UI optimization data) ────────────────────

    def is_search_or_read_command(self, input: Any) -> dict[str, bool]: ...

    # ── Observable input mutator (for SDK observers) ────────────────────────

    def backfill_observable_input(self, input: dict[str, Any]) -> None: ...

    # ── The actual call ─────────────────────────────────────────────────────

    @abstractmethod
    async def call(
        self,
        args: Any,
        context: ToolUseContext,
        can_use_tool: CanUseToolFn,
        parent_message: "AssistantMessage",
        on_progress: ToolCallProgress | None = None,
    ) -> ToolResult[OutputT]:
        """Execute the tool. Subclasses must implement."""
        ...


# ============================================================================
# Tool Defaults (matches TOOL_DEFAULTS in src/Tool.ts)
# ============================================================================


async def _default_check_permissions(
    input: dict[str, Any], _ctx: ToolUseContext
) -> PermissionResult:
    """Default permission check: allow, defer to general permission system."""
    return PermissionAllowDecision(behavior="allow", updatedInput=input)


def _default_is_enabled() -> bool:
    return True


def _default_is_concurrency_safe(_input: Any = None) -> bool:
    """Conservative default — assume not safe to parallelize."""
    return False


def _default_is_read_only(_input: Any = None) -> bool:
    """Conservative default — assume tool writes."""
    return False


def _default_is_destructive(_input: Any = None) -> bool:
    return False


def _default_to_auto_classifier_input(_input: Any = None) -> str:
    """Skip classifier by default. Security-relevant tools must override."""
    return ""


# ============================================================================
# Convenient Base Class
# ============================================================================
# Most tools subclass BaseTool to inherit the defaults.
# Override methods explicitly as needed. This is the Python equivalent of
# `buildTool({...def, ...TOOL_DEFAULTS})` from src/Tool.ts.


@dataclass
class Tools:
    """A collection of tools. Use this instead of bare list[Tool]."""
    tools: list[Tool] = field(default_factory=list)

    def __iter__(self):
        return iter(self.tools)

    def __len__(self):
        return len(self.tools)

    def find(self, name: str) -> Tool | None:
        return find_tool_by_name(self, name)


def tool_matches_name(tool: Tool, name: str) -> bool:
    """Check if a tool matches the given name (primary or alias)."""
    if tool.name == name:
        return True
    aliases = getattr(tool, "aliases", None) or []
    return name in aliases


def find_tool_by_name(tools: Tools, name: str) -> Tool | None:
    """Find a tool by name or alias from a list of tools."""
    for t in tools:
        if tool_matches_name(t, name):
            return t
    return None


class BaseTool(Generic[InputT, OutputT]):
    """
    Convenience base class for tools.

    Provides default implementations for capability flags, permission checks,
    and input observers. Subclasses must define `name`, `inputSchema`,
    `maxResultSizeChars`, and implement `call()`. Other methods can be
    overridden as needed.
    """

    # Required class attributes — subclasses MUST define.
    name: str = ""
    inputSchema: type[BaseModel]
    maxResultSizeChars: int = 100_000

    # Optional metadata.
    aliases: list[str] | None = None
    searchHint: str | None = None
    shouldDefer: bool = False
    alwaysLoad: bool = False
    strict: bool = False
    mcpInfo: dict[str, str] | None = None
    isMcp: bool = False
    isLsp: bool = False

    # ── Defaults ────────────────────────────────────────────────────────────

    def is_enabled(self) -> bool:
        return _default_is_enabled()

    def is_concurrency_safe(self, input: Any = None) -> bool:
        return _default_is_concurrency_safe(input)

    def is_read_only(self, input: Any = None) -> bool:
        return _default_is_read_only(input)

    def is_destructive(self, input: Any = None) -> bool:
        return _default_is_destructive(input)

    def is_open_world(self, input: Any = None) -> bool:
        return False

    def requires_user_interaction(self) -> bool:
        return False

    def interrupt_behavior(self) -> str:
        return "block"

    async def validate_input(
        self, input: Any, context: ToolUseContext
    ) -> ValidationResult:
        return ValidationOk()

    async def check_permissions(
        self, input: Any, context: ToolUseContext
    ) -> PermissionResult:
        return await _default_check_permissions(input, context)

    async def prepare_permission_matcher(
        self, input: Any
    ) -> Callable[[str], bool]:
        # Default: only tool-name-level matching works (returns False for any pattern).
        return lambda _pattern: False

    def get_path(self, input: Any) -> str | None:
        return None

    def input_json_schema(self) -> dict[str, Any] | None:
        # Default: derive from pydantic input schema.
        if self.inputSchema is None:
            return None
        return self.inputSchema.model_json_schema()

    def output_schema(self) -> type[BaseModel] | None:
        return None

    def inputs_equivalent(self, a: Any, b: Any) -> bool:
        return a == b

    async def description(self, input: Any, options: dict[str, Any]) -> str:
        return ""

    async def prompt(self, options: dict[str, Any]) -> str:
        return ""

    def user_facing_name(self, input: Any = None) -> str:
        return self.name

    def map_tool_result_to_block(
        self, content: Any, tool_use_id: str
    ) -> dict[str, Any]:
        # Default: serialize content as text.
        return {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": str(content) if content is not None else "",
        }

    def to_auto_classifier_input(self, input: Any) -> Any:
        return _default_to_auto_classifier_input(input)

    def is_search_or_read_command(self, input: Any) -> dict[str, bool]:
        return {"isSearch": False, "isRead": False, "isList": False}

    def backfill_observable_input(self, input: dict[str, Any]) -> None:
        # Default: no-op. Override to add legacy/derived fields in place.
        pass

    @abstractmethod
    async def call(
        self,
        args: Any,
        context: ToolUseContext,
        can_use_tool: CanUseToolFn,
        parent_message: Any,
        on_progress: ToolCallProgress | None = None,
    ) -> ToolResult:
        """Subclasses must implement."""
        raise NotImplementedError(f"{self.__class__.__name__}.call() not implemented")
