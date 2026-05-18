"""AgentTool — backend half (Phase 6.B.1.3 + 6.B.1.7 resume).

Port of `Utilities/claude files/software agent/src/tools/AgentTool/AgentTool.tsx`.
Source ships ~1400 lines covering coordinator mode, fork subagents, async
background tasks, worktree isolation, remote launch, and teammate spawn.
v1 ports ONLY the sync named path:

  - inputSchema (sync subset)
  - prompt() — delegates to .prompt.get_prompt
  - call() — sync named path:
      * Resume detection (Phase 6.B.1.7): if context.client_state.pending_subagents
        contains a frame for this tool_use_id, drive the resume path that
        feeds the frame's accumulatedMessages back into run_agent.
      * Fresh dispatch: validate, resolve agent, build prompt_messages,
        drive run_agent, capture pending frontend tool_uses.
      * On Terminal(awaiting_frontend_tools): build PendingSubagentFrame,
        raise SubagentAwaitingFrontendTools so query_loop can lift the
        dispatch into the parent's tool_request envelope.
      * On Terminal(completed): finalize and return.

Deferred branches (each guarded so callers learn at call time):
  - run_in_background — async dispatch (v2)
  - name / team_name  — teammate spawn (v2)
  - isolation         — worktree (v2) / remote (permanently excluded)
  - cwd               — never supported in edwin
  - fork (subagent_type omitted) — gated by forkSubagent.is_fork_subagent_enabled
"""

from __future__ import annotations

import time
from typing import Any

from app_logger import get_logger
from pydantic import BaseModel, Field

from ...services.agents import (
    filter_agents_by_mcp_requirements,
    has_required_mcp_servers,
    is_built_in_agent,
)
from ...Tool import (
    BaseTool,
    ToolProgress,
    ToolResult,
    ToolUseContext,
    ValidationError,
    ValidationOk,
    ValidationResult,
)
from ...types.hooks import CanUseToolFn
from ...types.ids import create_agent_id
from ...utils.messages import create_user_message
from .agentToolUtils import finalize_agent_tool
from .constants import AGENT_TOOL_NAME, LEGACY_AGENT_TOOL_NAME
from .exceptions import SubagentAwaitingFrontendTools
from .forkSubagent import is_fork_subagent_enabled
from .prompt import get_prompt as get_agent_tool_prompt
from .runAgent import run_agent
from .types import PendingSubagentFrame

log = get_logger(__name__)


# ============================================================================
# Schema
# ============================================================================


class AgentToolInput(BaseModel):
    """Sync fields:
      description — 3-5 word task summary (model-facing description)
      prompt      — the actual task to give the agent
      subagent_type — selects an active agent by agentType; defaults to
                       'general-purpose' when omitted

    Deferred (raise at call time): run_in_background, model, name,
    team_name, mode, isolation, cwd.
    """

    description: str = Field(description="A short (3-5 word) description of the task")
    prompt: str = Field(description="The task for the agent to perform")
    subagent_type: str | None = Field(
        default=None,
        description="The type of specialized agent to use for this task",
    )

    model_config = {"extra": "allow"}


# ============================================================================
# Resolution helpers
# ============================================================================


def _resolve_active_agents(
    context: ToolUseContext,
) -> tuple[list[dict[str, Any]], list[str] | None]:
    """Pull (active_agents, allowed_agent_types) from the merged-on-this-turn
    AgentDefinitionsResult sitting on ``context.options.agentDefinitions``."""
    result = getattr(context.options, "agentDefinitions", None)
    if result is None:
        return [], None
    if isinstance(result, dict):
        active = result.get("activeAgents")
        allowed = result.get("allowedAgentTypes")
    else:
        active = getattr(result, "activeAgents", None)
        allowed = getattr(result, "allowedAgentTypes", None)
    return (active or []), allowed


def _resolve_selected_agent(
    subagent_type: str | None,
    context: ToolUseContext,
) -> dict[str, Any]:
    """Default to ``general-purpose`` when ``subagent_type`` is omitted (fork
    gate is hardcoded off). Apply the per-spec ``allowed_types`` restriction
    if present, then look up.
    """
    effective_type = subagent_type or "general-purpose"

    all_agents, allowed_types = _resolve_active_agents(context)

    if allowed_types:
        candidate_agents = [
            a for a in all_agents if a.get("agentType") in set(allowed_types)
        ]
    else:
        candidate_agents = list(all_agents)

    found = next(
        (a for a in candidate_agents if a.get("agentType") == effective_type),
        None,
    )
    if found is not None:
        return found

    available = ", ".join(a.get("agentType", "") for a in candidate_agents)
    raise ValueError(
        f"Agent type '{effective_type}' not found. Available agents: {available}"
    )


def _check_required_mcp_servers(
    selected_agent: dict[str, Any], context: ToolUseContext  # noqa: ARG001
) -> None:
    """Point-in-time check against the manager's currently-connected servers.
    Raises ValueError if any required server is missing.
    """
    required = selected_agent.get("requiredMcpServers")
    if not required:
        return

    from ...services.mcp.connection_manager import maybe_get_manager

    available_servers: list[str] = []
    mgr = maybe_get_manager()
    if mgr is not None:
        try:
            for srv in mgr.list_servers():
                if srv.connected and srv.name not in available_servers:
                    available_servers.append(srv.name)
        except Exception as exc:  # noqa: BLE001
            log.warning("agent_tool_mcp_lookup_failed", extra={"error": str(exc)})

    if has_required_mcp_servers(selected_agent, available_servers):
        return

    available_lower = [s.lower() for s in available_servers]
    missing = [
        pat for pat in required if not any(pat.lower() in s for s in available_lower)
    ]
    raise ValueError(
        f"Agent '{selected_agent.get('agentType')}' requires MCP servers "
        f"matching: {', '.join(missing)}. MCP servers with tools: "
        f"{', '.join(available_servers) if available_servers else 'none'}."
    )


def _get_pending_bucket(context: ToolUseContext) -> list[Any]:
    """Read pending_subagents off the ClientState back-reference. Returns
    an empty list when no client_state is attached (e.g. during a
    one-shot tool test) — the caller treats empty as "no resume to do"."""
    cs = getattr(context, "client_state", None)
    if cs is None:
        return []
    return getattr(cs, "pending_subagents", None) or []


def _get_consumed_ledger(context: ToolUseContext) -> list[str] | None:
    """Same indirection for the consumed-ids ledger. Returns the live list
    so callers can append in place; None when no client_state is attached."""
    cs = getattr(context, "client_state", None)
    if cs is None:
        return None
    return getattr(cs, "consumed_subagent_tool_use_ids", None)


def _emit_agent_progress_for_message(
    event: Any,
    *,
    on_progress: Any,
    tool_use_id: str,
    agent_id: str,
    prompt: str = "",
) -> None:
    """Walk a subagent message's content blocks and fire ``on_progress`` once
    per ``tool_use`` or ``tool_result`` block. Pure-text messages don't fire —
    the chat-ui only needs to surface activity that demonstrates work. Errors
    are swallowed so a UI rendering failure can't break tool execution.

    The progress payload shape:
      ``{type, agentId, prompt, message}``
    The frontend dedupes by message uuid and renders one row per qualifying
    block under the parent's Agent tool block.
    """
    if on_progress is None or not tool_use_id:
        return
    if not isinstance(event, dict):
        return
    inner = event.get("message")
    if not isinstance(inner, dict):
        return
    content = inner.get("content")
    if not isinstance(content, list):
        return
    has_qualifying = any(
        isinstance(b, dict) and b.get("type") in ("tool_use", "tool_result")
        for b in content
    )
    if not has_qualifying:
        return
    try:
        on_progress(ToolProgress(
            toolUseID=tool_use_id,
            data={
                "type": "agent_progress",
                "message": event,
                "prompt": prompt,
                "agentId": agent_id,
            },
        ))
    except Exception:  # noqa: BLE001
        log.exception("agent_tool_progress_forward_failed")


# ============================================================================
# Tool
# ============================================================================


_STATIC_DESCRIPTION = (
    "Launch a new subagent to handle complex, multi-step tasks autonomously. "
    "Each agent runs in an isolated sub-loop with its own system prompt and "
    "tool sandbox, then returns a single final message you can act on. "
    "You cannot have a back-and-forth conversation with a running agent — "
    "provide enough context in `prompt` for it to complete the task on its own.\n"
    "\n"
    "Available agent types:\n"
    "  - general-purpose: broad multi-tool agent. Use for focused investigation "
    "or delimited multi-step tasks that should run with full tool access.\n"
    "  - Explore: read-only investigation specialist (ReadSlide, ListSlides, "
    "WebSearch/WebFetch, memory reads). Use to locate slides or content "
    "without mutating anything. Returns once.\n"
    "  - Plan: planning specialist (read tools + TodoWrite + ExitPlanMode). "
    "Use to draft an approach and submit it for approval before any changes "
    "are made.\n"
    "\n"
    "Args:\n"
    "  - description: 3-5 word summary of the task.\n"
    "  - prompt: the actual task for the agent to perform. Include enough "
    "context that the agent can run to completion without further input.\n"
    "  - subagent_type: which agent to dispatch (one of the types above). "
    "Defaults to general-purpose when omitted."
)


class AgentToolImpl(BaseTool[AgentToolInput, dict]):
    name = AGENT_TOOL_NAME
    aliases = [LEGACY_AGENT_TOOL_NAME]
    inputSchema = AgentToolInput
    maxResultSizeChars = 100_000
    searchHint = "delegate work to a subagent"
    # Static fallback description shipped to the LLM via the tool-schema
    # builder (claude.py:_build_tools_dict reads this attribute). The richer
    # ``prompt()`` method below produces the same content dynamically (with
    # MCP-requirement filtering applied); both are kept so callers that
    # invoke prompt() get the live filtered listing, while the static
    # attribute keeps the tool visible to providers that only consume
    # description_text.
    description_text = _STATIC_DESCRIPTION

    def is_enabled(self) -> bool:
        return True

    def is_concurrency_safe(self, input: Any = None) -> bool:
        # Multiple in-flight pending_subagents frames keyed by parentToolUseId
        # support concurrent dispatch — two parallel sync Agent() calls in
        # one assistant message dispatch independently and pause/resume
        # without collision.
        return True

    def is_read_only(self, input: Any = None) -> bool:
        return False

    def user_facing_name(self, input: Any = None) -> str:
        return "Agent"

    def map_tool_result_to_block(
        self, content: Any, tool_use_id: str
    ) -> dict[str, Any]:
        """Override of ``BaseTool.map_tool_result_to_block`` — the default
        does ``str(content)`` which on AgentTool's sync_output dict produces
        a Python repr littered with metadata noise. We extract
        ``content.content`` (the canonical Anthropic content block list
        built by ``finalize_agent_tool``) and ship that directly."""
        if isinstance(content, dict):
            inner = content.get("content")
            if isinstance(inner, list):
                return {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": inner,
                }
        if isinstance(content, str):
            return {
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": content,
            }
        return {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": "",
        }

    async def description(self, input: Any, options: Any) -> str:
        return "Launch a new agent"

    async def prompt(self, options: dict[str, Any]) -> str:
        """Filter active agents by:
          1. MCP requirements (each required server must be available)
        Then delegate to get_agent_tool_prompt for the actual prose.

        When ``agents`` isn't supplied in options (e.g. when the tool-schema
        builder calls us without knowing the registry), fall back to
        ``merge_agent_definitions()`` so the LLM still gets a live agent
        listing. Callers that DO know the registry should pass it so the
        per-spec ``allowedAgentTypes`` restriction can apply.
        """
        agents = options.get("agents")
        if not agents:
            from ...services.agents import merge_agent_definitions  # lazy
            agents = merge_agent_definitions().get("activeAgents", [])
        tools = options.get("tools") or []
        allowed_agent_types = options.get("allowed_agent_types")

        # Discover MCP servers that have tools loaded; format
        # ``mcp__serverName__toolName`` is the canonical convention.
        mcp_servers_with_tools: list[str] = []
        for tool in tools:
            tool_name = getattr(tool, "name", "") or ""
            if tool_name.startswith("mcp__"):
                parts = tool_name.split("__")
                if len(parts) >= 2 and parts[1] not in mcp_servers_with_tools:
                    mcp_servers_with_tools.append(parts[1])

        agents_with_mcp = filter_agents_by_mcp_requirements(
            agents, mcp_servers_with_tools
        )
        return await get_agent_tool_prompt(
            agents_with_mcp,
            is_coordinator=None,
            allowed_agent_types=allowed_agent_types,
        )

    async def validate_input(
        self, input: Any, context: ToolUseContext
    ) -> ValidationResult:
        active, _ = _resolve_active_agents(context)
        if not active:
            return ValidationError(
                message=(
                    "No agent definitions are loaded for this turn. Backend "
                    "wiring issue: ensure the per-turn router populates "
                    "options.agentDefinitions before the agent loop."
                ),
                errorCode=1,
            )
        return ValidationOk()

    async def call(
        self,
        args: Any,
        context: ToolUseContext,
        can_use_tool: CanUseToolFn,
        parent_message: Any,  # noqa: ARG002
        on_progress: Any | None = None,
    ) -> ToolResult[dict]:
        """Sync named path with Phase 6.B.1.7 resume detection.

        When the parent's Agent tool_use was orphaned in a prior /turn
        (subagent paused on awaiting_frontend_tools),
        ``ClientState.pending_subagents`` holds the frame keyed by
        ``parentToolUseId`` (= our ``context.toolUseId``). On resume we
        skip the front gate and feed the frame's accumulatedMessages —
        which the router pre-loop has already augmented with the freshly-
        delivered tool_results — straight into run_agent.
        """
        my_tool_use_id = getattr(context, "toolUseId", None) or ""
        pending_bucket = _get_pending_bucket(context)
        resume_frame: PendingSubagentFrame | None = None
        for f in pending_bucket:
            # Resume only frames AgentTool authored. SkillTool's fork lane
            # tags its own frames with originatingTool="Skill" — those are
            # picked up by SkillTool._call_fork_resume, not here. Frames
            # without the field were authored by AgentTool (back-compat
            # default before the fork lane existed).
            if not isinstance(f, dict):
                continue
            if f.get("originatingTool") not in (None, "Agent"):
                continue
            if (
                f.get("parentToolUseId") == my_tool_use_id
                and my_tool_use_id
            ):
                resume_frame = f
                break

        if resume_frame is not None:
            return await self._call_resume(
                resume_frame=resume_frame,
                pending_bucket=pending_bucket,
                context=context,
                can_use_tool=can_use_tool,
                on_progress=on_progress,
            )

        return await self._call_fresh(
            args=args,
            context=context,
            can_use_tool=can_use_tool,
            on_progress=on_progress,
        )

    async def _call_fresh(
        self,
        *,
        args: Any,
        context: ToolUseContext,
        can_use_tool: CanUseToolFn,
        on_progress: Any | None = None,
    ) -> ToolResult[dict]:
        parsed: AgentToolInput = (
            args if isinstance(args, AgentToolInput) else AgentToolInput(**(args or {}))
        )

        prompt = parsed.prompt
        description = parsed.description
        subagent_type = parsed.subagent_type

        # Deferred-feature guards — raise EARLY so we never silently accept
        # arguments that no code path implements.
        raw = args if isinstance(args, dict) else parsed.model_dump()
        if raw.get("run_in_background") is True:
            raise ValueError("run_in_background is not yet supported (v2).")
        if raw.get("name") or raw.get("team_name"):
            raise ValueError("Teammate spawn (`name` / `team_name`) is not yet supported.")
        if raw.get("isolation"):
            raise ValueError("isolation is not yet supported.")
        if raw.get("cwd"):
            raise ValueError("cwd override is not supported in edwin.")

        if subagent_type is None and is_fork_subagent_enabled():
            raise ValueError("Fork path is enabled but unimplemented.")

        selected_agent = _resolve_selected_agent(subagent_type, context)
        _check_required_mcp_servers(selected_agent, context)

        prompt_messages = [create_user_message(prompt)]
        agent_id = create_agent_id(label=selected_agent.get("agentType"))

        # Worker tool pool — assemble fresh per-turn so MCP changes are
        # reflected.
        from ...tools_registry import get_all_base_tools  # lazy: avoids cycle

        worker_pool = get_all_base_tools()
        start_time_ms = int(time.time() * 1000)

        # Initial kickoff emit: send the user(prompt) message via on_progress
        # BEFORE the iterator starts, so chat-ui captures the kickoff
        # message in the subagent activity stream. The kickoff carries the
        # prompt itself so the UI can render it as the first row; later
        # emits use prompt="" because only the first emission needs it.
        my_tool_use_id = getattr(context, "toolUseId", None) or ""
        if on_progress is not None and my_tool_use_id and prompt_messages:
            first_user = next(
                (
                    m for m in prompt_messages
                    if isinstance(m, dict) and m.get("type") == "user"
                ),
                None,
            )
            if first_user is not None:
                try:
                    on_progress(ToolProgress(
                        toolUseID=my_tool_use_id,
                        data={
                            "type": "agent_progress",
                            "message": first_user,
                            "prompt": prompt,
                            "agentId": str(agent_id),
                        },
                    ))
                except Exception:  # noqa: BLE001
                    log.exception("agent_tool_progress_forward_failed")

        # Drive the subagent loop, accumulate messages we care about for
        # finalize_agent_tool, capture in-flight frontend tool dispatches.
        from ...query.transitions import Terminal as _Terminal

        agent_messages, pending_by_id, final_terminal = await self._drain_run_agent(
            agent_definition=selected_agent,
            prompt_messages=prompt_messages,
            context=context,
            can_use_tool=can_use_tool,
            available_tools=worker_pool,
            description=description,
            agent_id=agent_id,
            on_progress=on_progress,
            parent_tool_use_id=my_tool_use_id,
        )

        # Pause path: subagent yielded awaiting_frontend_tools or
        # tool_request. Build the frame + raise so query_loop's
        # _execute_single_tool can lift the dispatch into the parent's
        # tool_request envelope.
        if final_terminal is not None and final_terminal.reason in (
            "awaiting_frontend_tools",
            "tool_request",
        ):
            pending_tool_uses = list(pending_by_id.values())
            frame: PendingSubagentFrame = {
                "agentId": str(agent_id),
                "agentType": selected_agent.get("agentType", ""),
                "parentToolUseId": "",  # query_loop catch site stamps
                "accumulatedMessages": agent_messages,
                "pendingToolUseIds": [
                    tu.get("id", "") for tu in pending_tool_uses if tu.get("id")
                ],
                "kickoffPrompt": prompt,
                "startTimeMs": start_time_ms,
                "description": description,
            }
            log.info(
                "agent_tool_pause",
                extra={
                    "agentType": selected_agent.get("agentType"),
                    "agentId": str(agent_id),
                    "pendingCount": len(pending_tool_uses),
                    "accumulatedMessageCount": len(agent_messages),
                },
            )
            raise SubagentAwaitingFrontendTools(
                frame=frame, tool_uses=pending_tool_uses
            )

        result_body = finalize_agent_tool(
            agent_messages,
            agent_id=str(agent_id),
            metadata={
                "prompt": prompt,
                "resolvedAgentModel": selected_agent.get("model"),
                "isBuiltInAgent": is_built_in_agent(selected_agent),
                "startTime": start_time_ms,
                "agentType": selected_agent.get("agentType"),
            },
        )

        sync_output = {
            "status": "completed",
            "prompt": prompt,
            **result_body,
        }
        log.info(
            "agent_tool_complete",
            extra={
                "agentType": selected_agent.get("agentType"),
                "agentId": str(agent_id),
                "messageCount": len(agent_messages),
                "tokens": result_body.get("totalTokens"),
            },
        )
        return ToolResult(data=sync_output)

    async def _call_resume(
        self,
        *,
        resume_frame: PendingSubagentFrame,
        pending_bucket: list[Any],
        context: ToolUseContext,
        can_use_tool: CanUseToolFn,
        on_progress: Any | None = None,
    ) -> ToolResult[dict]:
        """Resume a paused subagent from its persisted frame.

        Phase 6.B.1.7. The frame's ``accumulatedMessages`` already contains:
        subagent's user(prompt) → assistant(tool_use) → user(tool_results,
        injected by router pre-loop). We feed those straight to run_agent
        which drives query() onward — same drain pattern as fresh; same
        pause/complete branches.
        """
        from ...query.transitions import Terminal as _Terminal
        from ...services.agents import merge_agent_definitions
        from ...tools_registry import get_all_base_tools

        agent_type = resume_frame.get("agentType", "")
        agent_id_str = resume_frame.get("agentId", "")
        prompt = resume_frame.get("kickoffPrompt", "")
        description = resume_frame.get("description", "")
        start_time_ms = int(resume_frame.get("startTimeMs", 0))
        accumulated_messages = list(resume_frame.get("accumulatedMessages") or [])

        # Re-resolve the agent definition from the registry. Defensive:
        # built-in only in edwin v1; the agent type should always resolve.
        registry = merge_agent_definitions()
        selected_agent: dict[str, Any] | None = None
        for a in registry.get("activeAgents", []):
            if a.get("agentType") == agent_type:
                selected_agent = a
                break
        if selected_agent is None:
            log.warning(
                "agent_tool_resume_unknown_agent_type",
                extra={
                    "agentType": agent_type,
                    "agentId": agent_id_str,
                },
            )
            # Migrate the frame's pending tool_use_ids to the consumed-
            # ledger so the next /turn's router strips the tool_results
            # chat-ui sends back. Without this migration the tool_results
            # have no matching frame AND no consumed-set entry → router
            # would pass them through to the LLM → 400.
            stale_pending_ids = list(resume_frame.get("pendingToolUseIds") or [])
            consumed = _get_consumed_ledger(context)
            if consumed is not None and stale_pending_ids:
                seen = set(consumed)
                for tid in stale_pending_ids:
                    if tid and tid not in seen:
                        consumed.append(tid)
                        seen.add(tid)
            try:
                pending_bucket.remove(resume_frame)
            except ValueError:
                pass
            return ToolResult(data={
                "status": "completed",
                "prompt": prompt,
                "agentId": agent_id_str,
                "agentType": agent_type,
                "content": [{
                    "type": "text",
                    "text": (
                        f"Subagent resume failed: agent type '{agent_type}' "
                        "is no longer registered. The pending state was "
                        "discarded; ask the user to re-issue the request."
                    ),
                }],
                "totalDurationMs": 0,
                "totalTokens": 0,
                "totalToolUseCount": 0,
                "usage": {},
            })

        # Remove the old frame BEFORE driving the loop. If the subagent
        # pauses again, the catch in query_loop._execute_single_tool will
        # append the new frame fresh — we don't want stale duplicates
        # accumulating.
        try:
            pending_bucket.remove(resume_frame)
        except ValueError:
            pass

        worker_pool = get_all_base_tools()

        log.info(
            "agent_tool_resume",
            extra={
                "agentType": agent_type,
                "agentId": agent_id_str,
                "accumulatedMessageCount": len(accumulated_messages),
            },
        )

        # Resume replay: forward the accumulated history via on_progress so
        # chat-ui's subagent activity picks up the user(tool_result) message
        # injected by the router pre-loop. ``run_agent`` only yields NEW
        # events it produces — without this replay the nested tool_use
        # blocks would spin forever on the UI (their results sit in
        # accumulated_messages but never reach the frontend). Frontend
        # dedupes by message uuid, so re-sending entries it already saw
        # on the prior /turn is safe.
        resume_parent_id = getattr(context, "toolUseId", None) or ""
        if on_progress is not None and resume_parent_id:
            for accumulated_event in accumulated_messages:
                if not isinstance(accumulated_event, dict):
                    continue
                if accumulated_event.get("type") not in ("user", "assistant"):
                    continue
                _emit_agent_progress_for_message(
                    accumulated_event,
                    on_progress=on_progress,
                    tool_use_id=resume_parent_id,
                    agent_id=agent_id_str,
                )

        agent_messages, pending_by_id, final_terminal = await self._drain_run_agent(
            agent_definition=selected_agent,
            prompt_messages=accumulated_messages,
            context=context,
            can_use_tool=can_use_tool,
            available_tools=worker_pool,
            description=description,
            agent_id=agent_id_str,  # Reuse — keeps finalize agentId stable
            on_progress=on_progress,
            parent_tool_use_id=resume_parent_id,
        )

        # Pause again: build new frame from the latest accumulated messages
        # (which now include this resume iteration's assistant message +
        # any new frontend tool_uses).
        if final_terminal is not None and final_terminal.reason in (
            "awaiting_frontend_tools",
            "tool_request",
        ):
            pending_tool_uses = list(pending_by_id.values())
            new_frame: PendingSubagentFrame = {
                "agentId": agent_id_str,
                "agentType": agent_type,
                "parentToolUseId": "",  # query_loop catch site stamps
                "accumulatedMessages": accumulated_messages + agent_messages,
                "pendingToolUseIds": [
                    tu.get("id", "") for tu in pending_tool_uses if tu.get("id")
                ],
                "kickoffPrompt": prompt,
                "startTimeMs": start_time_ms,
                "description": description,
            }
            log.info(
                "agent_tool_repause",
                extra={
                    "agentType": agent_type,
                    "agentId": agent_id_str,
                    "pendingCount": len(pending_tool_uses),
                    "accumulatedMessageCount": len(new_frame["accumulatedMessages"]),
                },
            )
            raise SubagentAwaitingFrontendTools(
                frame=new_frame, tool_uses=pending_tool_uses
            )

        # Completion: finalize over the FULL message history (resumed
        # accumulated + this iteration's new messages).
        full_messages = accumulated_messages + agent_messages
        result_body = finalize_agent_tool(
            full_messages,
            agent_id=agent_id_str,
            metadata={
                "prompt": prompt,
                "resolvedAgentModel": selected_agent.get("model"),
                "isBuiltInAgent": is_built_in_agent(selected_agent),
                "startTime": start_time_ms,
                "agentType": agent_type,
            },
        )
        sync_output = {
            "status": "completed",
            "prompt": prompt,
            **result_body,
        }
        log.info(
            "agent_tool_complete_after_resume",
            extra={
                "agentType": agent_type,
                "agentId": agent_id_str,
                "messageCount": len(full_messages),
                "tokens": result_body.get("totalTokens"),
            },
        )
        # Bounded-edge cleanup: when this resume drained the last frame,
        # the consumed-ids ledger is no longer protecting any active
        # subagent. Clear so it doesn't grow unboundedly across the chat
        # lifetime. When multiple frames are in flight, we only clear
        # when ALL drain — any earlier completion's ids stay in the
        # ledger until the last frame finishes (correct, since router
        # still needs to filter them while other frames are active).
        cs = getattr(context, "client_state", None)
        if cs is not None:
            ledger_pending = getattr(cs, "pending_subagents", None) or []
            ledger_consumed = getattr(cs, "consumed_subagent_tool_use_ids", None)
            if not ledger_pending and isinstance(ledger_consumed, list) and ledger_consumed:
                ledger_consumed.clear()
        return ToolResult(data=sync_output)

    async def _drain_run_agent(
        self,
        *,
        agent_definition: dict[str, Any],
        prompt_messages: list[Any],
        context: ToolUseContext,
        can_use_tool: CanUseToolFn,
        available_tools: Any,
        description: str,
        agent_id: Any,
        on_progress: Any | None = None,
        parent_tool_use_id: str = "",
    ) -> tuple[list[Any], dict[str, dict[str, Any]], Any]:
        """Drain the subagent's event stream, returning
        (accumulated_messages, pending_by_id, final_terminal).

        Captures frontend tool dispatches in TWO shapes:
          1. ``tool_dispatch`` events emitted MID-STREAM, one per tool, the
             moment a frontend tool's input is fully streamed.
          2. ``tool_request`` events emitted POST-STREAM as a batched
             stragglers payload for any tool that slipped past mid-stream
             dispatch.
        Both populate ``pending_by_id`` keyed by id (dedupe).
        """
        from ...query.transitions import Terminal as _Terminal

        agent_messages: list[Any] = []
        pending_by_id: dict[str, dict[str, Any]] = {}
        final_terminal: _Terminal | None = None

        async for event in run_agent(
            agent_definition=agent_definition,
            prompt_messages=prompt_messages,
            tool_use_context=context,
            can_use_tool=can_use_tool,
            available_tools=available_tools,
            description=description,
            agent_id=agent_id,
            model=None,
        ):
            if isinstance(event, _Terminal):
                final_terminal = event
                continue
            if isinstance(event, dict):
                etype = event.get("type")
                if etype in ("user", "assistant"):
                    agent_messages.append(event)
                    # Forward subagent message activity to chat-ui via
                    # on_progress. Filter strictly: only emit when the
                    # message contains a tool_use OR tool_result content
                    # block — pure-text messages don't fire (matches TS
                    # source's filter). Frontend dedupes by message uuid.
                    _emit_agent_progress_for_message(
                        event,
                        on_progress=on_progress,
                        tool_use_id=parent_tool_use_id,
                        agent_id=str(agent_id),
                    )
                elif etype == "tool_dispatch":
                    call_id = event.get("call_id") or ""
                    if call_id and call_id not in pending_by_id:
                        pending_by_id[call_id] = {
                            "type": "tool_use",
                            "id": call_id,
                            "name": event.get("name", ""),
                            "input": event.get("input") or {},
                        }
                elif etype == "tool_request":
                    for tu in (event.get("parallel_calls") or []):
                        if isinstance(tu, dict):
                            tu_id = tu.get("tool_use_id") or tu.get("id") or ""
                            if tu_id and tu_id not in pending_by_id:
                                pending_by_id[tu_id] = {
                                    "type": "tool_use",
                                    "id": tu_id,
                                    "name": tu.get("tool_name") or tu.get("name", ""),
                                    "input": tu.get("tool_input") or tu.get("input") or {},
                                }
                    for tu in (event.get("sequential_calls") or []):
                        if isinstance(tu, dict):
                            tu_id = tu.get("tool_use_id") or tu.get("id") or ""
                            if tu_id and tu_id not in pending_by_id:
                                pending_by_id[tu_id] = {
                                    "type": "tool_use",
                                    "id": tu_id,
                                    "name": tu.get("tool_name") or tu.get("name", ""),
                                    "input": tu.get("tool_input") or tu.get("input") or {},
                                }

        return agent_messages, pending_by_id, final_terminal


AgentTool = AgentToolImpl()
