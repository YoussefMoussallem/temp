"""Pure helpers for AgentTool / runAgent.

Port of `Utilities/claude files/software agent/src/tools/AgentTool/agentToolUtils.ts`.
v1 ships the slice runAgent + AgentTool actually need:

  - resolve_agent_tools  — apply agent.tools / agent.disallowedTools to
    a parent tool pool.
  - count_tool_uses      — sum tool_use blocks across an assistant message
    stream.
  - get_last_assistant_message — last assistant message in a list, or None.
  - finalize_agent_tool  — assemble the AgentToolSyncOutput body from the
    collected subagent messages.

Telemetry (logEvent) intentionally dropped — billing/telemetry flow stays
untouched until the dedicated lane.
"""

from __future__ import annotations

import time
from typing import Any, NamedTuple

from ...Tool import Tool, Tools
from ..AgentTool.constants import AGENT_TOOL_NAME


# ============================================================================
# Tool resolution
# ============================================================================


class ResolvedAgentTools(NamedTuple):
    has_wildcard: bool
    valid_tools: list[str]
    invalid_tools: list[str]
    resolved_tools: list[Tool]
    allowed_agent_types: list[str] | None = None


# Tools that subagents must never see, regardless of allowlist. The Agent
# tool itself is removed to prevent recursive spawning. EnterPlanMode would
# join this set when it grows subagent-aware, but it's not yet ported.
_SUBAGENT_FORBIDDEN_TOOLS = frozenset({AGENT_TOOL_NAME})


def _filter_tools_for_agent(tools: list[Tool]) -> list[Tool]:
    """Drop tools subagents shouldn't see by default — chiefly the Agent
    tool itself (no recursive spawn). Built-ins declare further restrictions
    via ``disallowedTools`` which the outer caller applies."""
    return [t for t in tools if t.name not in _SUBAGENT_FORBIDDEN_TOOLS]


def _parse_tool_spec(spec: str) -> tuple[str, str | None]:
    """Extract ``(toolName, ruleContent)`` from ``Bash(prefix:*)``-style
    strings. Split on first ``(``; treat the inside-parens body as
    ruleContent."""
    open_paren = spec.find("(")
    if open_paren == -1:
        return spec, None
    tool_name = spec[:open_paren]
    body = spec[open_paren + 1:]
    if body.endswith(")"):
        body = body[:-1]
    return tool_name, body or None


def resolve_agent_tools(
    agent_definition: dict[str, Any],
    available_tools: Tools | list[Tool],
    is_main_thread: bool = False,
) -> ResolvedAgentTools:
    """Apply the agent's ``tools`` allowlist + ``disallowedTools`` denylist
    over the parent's tool pool, returning the resolved subset (plus
    bookkeeping for the AgentTool's downstream ``allowedAgentTypes``
    discovery from ``Agent(x,y)`` specs)."""
    agent_tools = agent_definition.get("tools")
    disallowed = agent_definition.get("disallowedTools") or []

    parent_pool: list[Tool] = (
        list(available_tools.tools)
        if hasattr(available_tools, "tools")
        else list(available_tools)
    )

    filtered_pool = parent_pool if is_main_thread else _filter_tools_for_agent(parent_pool)

    disallowed_names: set[str] = set()
    for spec in disallowed:
        name, _ = _parse_tool_spec(spec)
        disallowed_names.add(name)
    allowed_pool = [t for t in filtered_pool if t.name not in disallowed_names]

    has_wildcard = (
        agent_tools is None
        or (len(agent_tools) == 1 and agent_tools[0] == "*")
    )
    if has_wildcard:
        return ResolvedAgentTools(
            has_wildcard=True,
            valid_tools=[],
            invalid_tools=[],
            resolved_tools=allowed_pool,
            allowed_agent_types=None,
        )

    pool_by_name: dict[str, Tool] = {t.name: t for t in allowed_pool}
    valid: list[str] = []
    invalid: list[str] = []
    resolved: list[Tool] = []
    seen: set[Tool] = set()
    allowed_agent_types: list[str] | None = None

    for spec in agent_tools:
        tool_name, rule_content = _parse_tool_spec(spec)
        if tool_name == AGENT_TOOL_NAME:
            if rule_content:
                allowed_agent_types = [
                    s.strip() for s in rule_content.split(",") if s.strip()
                ]
            if not is_main_thread:
                # Already stripped by _filter_tools_for_agent for subagents.
                # Mark the spec valid (for allowedAgentTypes tracking) and
                # skip pool lookup.
                valid.append(spec)
                continue

        tool = pool_by_name.get(tool_name)
        if tool is not None:
            valid.append(spec)
            if tool not in seen:
                resolved.append(tool)
                seen.add(tool)
        else:
            invalid.append(spec)

    return ResolvedAgentTools(
        has_wildcard=False,
        valid_tools=valid,
        invalid_tools=invalid,
        resolved_tools=resolved,
        allowed_agent_types=allowed_agent_types,
    )


# ============================================================================
# Tool-use counting
# ============================================================================


def count_tool_uses(messages: list[Any]) -> int:
    """Total tool_use blocks across all assistant messages."""
    count = 0
    for m in messages:
        if not isinstance(m, dict):
            continue
        if m.get("type") != "assistant":
            continue
        content = (m.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                count += 1
    return count


# ============================================================================
# Agent message accessors
# ============================================================================


def get_last_assistant_message(messages: list[Any]) -> dict[str, Any] | None:
    """Last ``type == 'assistant'`` message, or None."""
    for m in reversed(messages):
        if isinstance(m, dict) and m.get("type") == "assistant":
            return m
    return None


def _extract_text_blocks(message: dict[str, Any]) -> list[dict[str, Any]]:
    content = (message.get("message") or {}).get("content")
    if not isinstance(content, list):
        return []
    return [
        b for b in content if isinstance(b, dict) and b.get("type") == "text"
    ]


def _get_token_count_from_usage(usage: dict[str, Any] | None) -> int:
    """Sum input + output + cache_creation + cache_read where set."""
    if not usage:
        return 0
    return (
        int(usage.get("input_tokens") or 0)
        + int(usage.get("output_tokens") or 0)
        + int(usage.get("cache_creation_input_tokens") or 0)
        + int(usage.get("cache_read_input_tokens") or 0)
    )


def finalize_agent_tool(
    agent_messages: list[Any],
    agent_id: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """Build the AgentToolSyncOutput body from the subagent's collected
    messages + run metadata.

    ``metadata`` keys: prompt, resolvedAgentModel, isBuiltInAgent, startTime
    (epoch ms), agentType.
    """
    last_assistant = get_last_assistant_message(agent_messages)
    if last_assistant is None:
        raise RuntimeError("runAgent finished with no assistant messages")

    # Final assistant may be a pure tool_use (loop exited mid-turn). Walk
    # backwards for the most recent one with text blocks.
    content = _extract_text_blocks(last_assistant)
    if not content:
        for m in reversed(agent_messages):
            if not isinstance(m, dict) or m.get("type") != "assistant":
                continue
            blocks = _extract_text_blocks(m)
            if blocks:
                content = blocks
                break

    usage = (last_assistant.get("message") or {}).get("usage") or {}
    total_tokens = _get_token_count_from_usage(usage)
    total_tool_uses = count_tool_uses(agent_messages)

    start_time_ms = int(metadata.get("startTime") or 0)
    duration_ms = max(0, int(time.time() * 1000) - start_time_ms)

    return {
        "agentId": agent_id,
        "agentType": metadata.get("agentType"),
        "content": content,
        "totalDurationMs": duration_ms,
        "totalTokens": total_tokens,
        "totalToolUseCount": total_tool_uses,
        "usage": usage,
    }
