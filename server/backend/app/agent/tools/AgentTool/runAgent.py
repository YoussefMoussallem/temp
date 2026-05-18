"""Subagent sub-loop runner — backend half (Phase 6.B.1.4 sync path).

Port of `Utilities/claude files/software agent/src/tools/AgentTool/runAgent.ts`.
v1 ships the SYNC slice that drives a subagent's ``query()`` loop:

  - Resolve agent ID + system prompt + tool subset
  - Build the subagent ToolUseContext (clones parent options, swaps the
    parent's per-turn system prompt for the agent's own, sets agentId +
    agentType so tools that need to detect subagent execution can branch)
  - Construct QueryParams for the subagent
  - Drive ``query()`` from query_loop.py — same engine the main /turn uses
  - Yield messages as they stream so the caller (AgentTool.call) can
    surface them upward

Async (run_in_background) wiring deferred to v2.
"""

from __future__ import annotations

import dataclasses
import time
from typing import Any, AsyncGenerator

from app_logger import get_logger

from ...Tool import Tool, Tools, ToolUseContext
from ...types.hooks import CanUseToolFn
from ...types.ids import AgentId, create_agent_id
from ...utils.model import get_agent_model
from .agentToolUtils import resolve_agent_tools

log = get_logger(__name__)


def _build_subagent_context(
    parent: ToolUseContext,
    agent_definition: dict[str, Any],
    agent_id: AgentId,
    resolved_model: str | None = None,
) -> ToolUseContext:
    """Clone the parent context with subagent overrides applied.

    Inherits parent's authorization, project_id, conversation_id, user_id,
    and client_state (so AgentTool's resume path can mutate
    pending_subagents on the same blob the parent will ship out).

    The subagent's system prompt is NOT carried on the context — it's
    passed directly to QueryParams.systemPrompt by the caller. This is
    cleaner than the source's customSystemPrompt indirection because
    edwin's QueryParams already accepts a per-call systemPrompt.
    """
    sub_options_kwargs: dict[str, Any] = {}
    if resolved_model:
        sub_options_kwargs["mainLoopModel"] = resolved_model
    sub_options = (
        dataclasses.replace(parent.options, **sub_options_kwargs)
        if sub_options_kwargs
        else dataclasses.replace(parent.options)
    )
    return dataclasses.replace(
        parent,
        options=sub_options,
        agentId=str(agent_id),
        agentType=agent_definition.get("agentType"),
    )


async def run_agent(
    *,
    agent_definition: dict[str, Any],
    prompt_messages: list[Any],
    tool_use_context: ToolUseContext,
    can_use_tool: CanUseToolFn,
    available_tools: Tools | list[Tool],
    description: str | None = None,
    agent_id: AgentId | None = None,
    model: str | None = None,
    max_turns: int | None = None,
    is_async: bool = False,
    query_source: str | None = None,
    override: dict[str, Any] | None = None,
) -> AsyncGenerator[Any, None]:
    """Drive the subagent's ``query()`` loop.

    Yields the same event stream that ``query()`` yields (messages,
    stream_events, terminals). The caller (``AgentTool.call``) is expected
    to:
      1. accumulate the messages it cares about
      2. forward stream events upward unchanged so the chat-ui can render
         the subagent's output live
      3. call ``finalize_agent_tool`` on the accumulated messages once the
         loop terminates

    Async (run_in_background) wiring deferred to v2.
    """
    # Lazy import — query_loop imports many tool modules and pulling it
    # from this module's import header risks circular imports.
    from ...query_loop import QueryParams, query

    if is_async:
        raise NotImplementedError(
            "run_agent: is_async=True (run_in_background subagents) is "
            "deferred to v2."
        )

    override_payload = override or {}
    override_agent_id = override_payload.get("agentId")
    if override_agent_id is not None:
        agent_id = override_agent_id  # type: ignore[assignment]

    if agent_id is None:
        agent_id = create_agent_id(label=agent_definition.get("agentType"))

    # Apply agent.tools allowlist + agent.disallowedTools denylist over the
    # parent's pool. Subagents never see the Agent tool itself (no recursive
    # spawn) — _filter_tools_for_agent handles that.
    resolved = resolve_agent_tools(
        agent_definition,
        available_tools,
        is_main_thread=False,
    )

    # Subagent's own prompt — agent definitions ship a getSystemPrompt
    # callable. Failure here is non-fatal (logged + empty prompt) so a
    # broken built-in doesn't hard-crash dispatch.
    get_system_prompt = agent_definition.get("getSystemPrompt")
    agent_system_prompt = ""
    if callable(get_system_prompt):
        try:
            agent_system_prompt = get_system_prompt(toolUseContext=tool_use_context) or ""
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "run_agent_system_prompt_failed",
                extra={
                    "agentType": agent_definition.get("agentType"),
                    "error": str(exc),
                },
            )

    # Resolve effective model: tool-specified > agent.model > parent's.
    parent_main_loop_model = (
        getattr(tool_use_context.options, "mainLoopModel", "") or ""
    )
    resolved_model = get_agent_model(
        agent_model=agent_definition.get("model"),
        parent_model=parent_main_loop_model,
        tool_specified_model=model,
    )

    sub_context = _build_subagent_context(
        tool_use_context,
        agent_definition,
        agent_id,
        resolved_model=resolved_model,
    )

    if query_source is not None:
        effective_query_source = query_source
    else:
        agent_source = (
            "builtin"
            if agent_definition.get("source") == "built-in"
            else agent_definition.get("source") or "unknown"
        )
        effective_query_source = (
            f"agent:{agent_source}:{agent_definition.get('agentType')}"
        )

    sub_params = QueryParams(
        messages=list(prompt_messages),
        tools=Tools(tools=list(resolved.resolved_tools)),
        canUseTool=can_use_tool,
        toolUseContext=sub_context,
        systemPrompt=agent_system_prompt,
        querySource=effective_query_source,
        maxTurns=max_turns,
    )

    log.info(
        "run_agent_dispatch",
        extra={
            "agentType": agent_definition.get("agentType"),
            "agentId": str(agent_id),
            "toolCount": len(resolved.resolved_tools),
            "promptMessageCount": len(prompt_messages),
            "description": description,
            "resolvedModel": resolved_model,
            "parentModel": parent_main_loop_model,
        },
    )

    started_at_ms = int(time.time() * 1000)
    try:
        async for event in query(sub_params):
            yield event
    finally:
        log.info(
            "run_agent_complete",
            extra={
                "agentType": agent_definition.get("agentType"),
                "agentId": str(agent_id),
                "durationMs": int(time.time() * 1000) - started_at_ms,
            },
        )
