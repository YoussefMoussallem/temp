"""
QueryEngine — orchestration wrapper for query().

Port of src/QueryEngine.ts. v1 implements the MINIMAL stateless wrapper:

  - Constructor accepts ClientState (opaque blob from chat-ui per Q5)
  - Hydrates the in-flight messages/state from ClientState
  - Runs query() once per turn
  - Updates ClientState shape with usage / messages mutations
  - Returns the updated ClientState (chat-ui stores it for next turn)

DEFERRED for later phases:
  - Cost accumulation (Phase 5 — separate from existing billing DB)
  - File history snapshots (Phase 6 — git-unified per Q6-G)
  - Transcript persistence (chat-ui handles per Q5)
  - Session resume (chat-ui localStorage per Q5)
  - Compaction state tracking (Phase 3)

Per stateless backend principle: NO singleton; new QueryEngine per /turn.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, AsyncGenerator

from .prompts import build_system_prompt_string, get_system_prompt
from .query_loop import State, QueryParams, query
from .query.deps import QueryDeps
from .query.transitions import Terminal
from .Tool import ToolUseContext, ToolUseContextOptions, Tools
from .types.hooks import CanUseToolFn


_PLAN_MODE_APPENDIX = """

---

## Plan Mode Instructions

You are currently in PLAN MODE. In this mode you MUST NOT call `CreateSlide`,
`UpdateSlide`, `DeleteSlide`, or `ReorderSlide`. Your job is to outline your
approach so the user can review and approve it before you act.

**Required steps in plan mode:**
1. Use `TodoWrite` to define all the steps you plan to take. Set status to "pending" for all.
2. Write a clear explanation of what each slide or section will contain.
3. As you reason through each step, update the corresponding todo to "in_progress", then "completed".
4. When your complete plan is ready, call `ExitPlanMode` with the full markdown plan.

Do NOT generate any slide content. Do NOT make changes. Outline only.
"""


def _build_mcp_appendix() -> str:
    """Short blurb listing connected MCP servers. Empty when none are live."""
    from .services.mcp.connection_manager import maybe_get_manager  # noqa: PLC0415

    mgr = maybe_get_manager()
    if mgr is None:
        return ""
    live = [s for s in mgr.list_servers() if s.connected]
    if not live:
        return ""
    lines = ["\n\n---\n\n## Available MCP servers\n"]
    for s in live:
        lines.append(f"- `{s.name}` ({len(s.tools)} tool(s))")
    lines.append(
        "\nCall tools from these servers via their namespaced names "
        "(`mcp__<server>__<tool>`). Use `ListMcpResources`/`ReadMcpResource` "
        "to discover and read the resources they expose."
    )
    return "\n".join(lines)


async def _build_skills_appendix() -> str:
    """Skills inventory — informs the LLM which skills it can invoke.

    Without this block the model has no way to know ``/outline-deck``
    exists; the SkillTool's tool description can't list every skill
    or it would explode token cost on every tool call. Phase 2.7b.2.

    Wrapped in try/except so a transient FS issue (permissions, race on
    user-skill upload) never bricks the system prompt — empty appendix
    is a graceful fallback.
    """
    try:
        from .skills.discovery import discover_skills  # noqa: PLC0415
        from .skills.inventory import render_skills_inventory  # noqa: PLC0415

        skills = await discover_skills(None)
        return render_skills_inventory(skills)
    except Exception:  # noqa: BLE001
        return ""


async def _build_system_prompt(
    permission_mode: str,
    tools: Tools,
    model: str,
) -> str:
    """Compose the per-turn system prompt: sections-based static prefix +
    appendices.

    The static prefix is built by
    :func:`agent.prompts.builder.get_system_prompt` from a registered
    set of section helpers (intro, system, doing-tasks, actions,
    using-tools, tone-and-style, output-efficiency). It's byte-stable
    across turns within a process so any prefix-cache the LLM proxy
    keeps can hit on subsequent turns.

    Three appendices append after the prefix:

    * Plan-mode constraints — when ``permission_mode == "plan"``.
      Appended (rather than folded into a section) because plan mode
      flips between turns; folding would invalidate the section cache.
    * Live MCP servers — synchronous read of the connection-manager
      state. Empty when no MCP servers are connected.
    * Discovered skills — filesystem read of bundled + user skills.
      Wrapped in try/except by ``_build_skills_appendix`` so a transient
      FS error never bricks the prompt.

    All three appendices are inherently dynamic per turn — they belong
    in the dynamic-tail of the section framework when that lands. For
    now they ride after the static prefix as plain string concatenation
    (the boundary marker is already inside ``system_array`` so the
    static-prefix region of the proxy cache stays intact regardless of
    appendix churn).
    """
    system_array = await get_system_prompt(
        tools=list(tools),
        model=model,
        additional_working_directories=None,
        mcp_clients=None,
    )
    base = build_system_prompt_string(system_array)
    if permission_mode == "plan":
        base = base + _PLAN_MODE_APPENDIX
    base = base + _build_mcp_appendix()
    base = base + await _build_skills_appendix()
    return base

if TYPE_CHECKING:
    from .types.message import Message


# ============================================================================
# ClientState — what chat-ui carries between turns (opaque to chat-ui)
# ============================================================================


@dataclass
class ClientState:
    """
    Opaque state blob round-tripped through chat-ui per Q5.

    Backend defines the shape; chat-ui stores it as-is and ships it back
    next turn. Chat-ui MUST NOT read or branch on field contents (per
    feedback_dumb_client).

    v1 fields are minimal — expand as features land.
    """
    iteration: int = 0
    # Compaction tracking (Phase 3).
    compact_tracking: dict[str, Any] = field(default_factory=dict)
    # Total tokens seen so far in this conversation.
    known_token_count: int = 0
    # Recovery counter (Phase 3).
    max_output_recovery_count: int = 0
    # Plan mode: "default" or "plan".
    permission_mode: str = "default"


# ============================================================================
# QueryEngine
# ============================================================================


@dataclass
class QueryEngine:
    """
    Orchestration wrapper around the agentic loop.

    Created fresh per /turn request (stateless backend). Hydrates from the
    chat-ui's opaque state blob, runs the loop, returns updated state.
    """

    # Hydrated from incoming /turn request.
    client_state: ClientState = field(default_factory=ClientState)
    # Tools available this turn.
    tools: Tools = field(default_factory=Tools)
    # Per-turn options (model, debug, verbose, etc.).
    options: ToolUseContextOptions = field(default_factory=ToolUseContextOptions)
    # Optional dependency-injected callables (tests, custom LLM).
    deps: QueryDeps | None = None

    async def run(
        self,
        messages: list["Message"],
        can_use_tool: CanUseToolFn,
        max_turns: int | None = None,
        authorization: str | None = None,
        project_id: str | None = None,
        command_uuids: list[str] | None = None,
    ) -> AsyncGenerator[Any, None]:
        """
        Run one /turn.

        Yields stream events + messages from the loop, plus the final Terminal.
        Caller (router.py) maps these to SSE events for chat-ui.
        """
        tool_use_context = ToolUseContext(
            options=self.options,
            messages=messages,
            authorization=authorization,
            project_id=project_id,
        )
        tool_use_context.options.permissionMode = self.client_state.permission_mode

        params = QueryParams(
            messages=messages,
            tools=self.tools,
            canUseTool=can_use_tool,
            toolUseContext=tool_use_context,
            systemPrompt=await _build_system_prompt(
                permission_mode=tool_use_context.options.permissionMode,
                tools=self.tools,
                model=tool_use_context.options.mainLoopModel,
            ),
            maxTurns=max_turns,
            deps=self.deps,
            command_uuids=list(command_uuids or []),
        )

        # Track iteration count in client_state (visible in opaque blob).
        terminal: Terminal | None = None
        async for event in query(params):
            if isinstance(event, Terminal):
                terminal = event
                yield event
                # Don't break — let the generator finish naturally.
            else:
                yield event

        # Persist permission mode back to client state for the next turn.
        self.client_state.permission_mode = tool_use_context.options.permissionMode

        # Update client_state for return trip.
        self.client_state.iteration += 1

        # Final state_update event so chat-ui can store the new opaque blob.
        yield {
            "type": "state_update",
            "client_state": self.client_state,
            "terminal": terminal,
        }

    def get_client_state(self) -> ClientState:
        """Return the current opaque state for chat-ui to store."""
        return self.client_state
