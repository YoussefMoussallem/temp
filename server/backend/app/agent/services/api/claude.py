"""
Claude API streaming bridge.

Port of src/services/api/claude.ts (3420 lines in source!) — minimal v1.

Bridges the agent loop to the existing ProviderAdapter infrastructure
(server/libs/llm_providers/). Two responsibilities:

  1. Translate loop-format messages/tools → ProviderMessage/dict (the
     adapter's input shape).
  2. Forward the adapter's stream events back, wrapping the final
     `assistant_message` event into the loop's expected `{type: "assistant",
     message: {...}}` shape — so query_loop stays adapter-agnostic.

Provider routing, prompt cache, retry/fallback, etc. live in
`provider_bridge.resolve_provider()` and the per-provider adapters —
DON'T duplicate.

Accumulation of stream events into a final assistant message lives in
the adapters (see `ProviderAdapter.stream` contract: emits
`assistant_message` before `done`). This file used to do that work,
which led to event-field-name drift bugs — moving it to the source of
truth (the adapter that emits the events) eliminated that bug class.

DEFERRED for later phases:
  - Prompt caching (cache_control headers) → Phase 3
  - Thinking blocks → Phase 3
  - Task budgets (output_config.task_budget) → Phase 3
  - Retry + fallback (src/services/api/withRetry.ts is 822 lines) → Phase 3
  - Streaming downgrade (FallbackTriggeredError) → Phase 3
  - Cost tracking accumulation → Phase 5
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, AsyncIterator

from app.bridges.provider_bridge import resolve_provider
from llm_provider.schemas import (
    ChatRequest,
    Message as ProviderMessage,
    ToolCallData as ProviderToolCall,
)

from ...Tool import Tools

if TYPE_CHECKING:
    from ...types.message import Message


# ============================================================================
# Message normalization (loop format → adapter format)
# ============================================================================


def _normalize_messages_for_api(messages: list["Message"]) -> list[ProviderMessage]:
    """
    Convert loop-format messages → ProviderMessage list.

    Loop format: {type: 'user'|'assistant'|'system', message: {role, content: str | list[block]}}
    Provider format: {role: 'user'|'assistant'|'tool', content, tool_calls, tool_call_id}

    Splits content blocks: tool_use → assistant tool_calls;
    tool_result → separate 'tool' role message.

    Mirrors src/utils/messages.ts:normalizeMessagesForAPI.
    """
    out: list[ProviderMessage] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue

        # Support two formats:
        #   Wrapped (from _build_messages): {type: "user", message: {role, content}}
        #   Flat (from frontend history):   {role: "user", content: "..."}
        if "message" in msg:
            msg_type = msg.get("type")
            if msg_type == "system":
                continue
            inner = msg["message"]
            role = inner.get("role", msg_type)
            content = inner.get("content")
        elif "role" in msg:
            role = msg["role"]
            if role == "system":
                continue
            content = msg.get("content")
        else:
            continue

        # Simple text message.
        if isinstance(content, str):
            out.append(ProviderMessage(role=role, content=content))
            continue

        if not isinstance(content, list):
            continue  # Skip malformed.

        # Walk content blocks; collect text + tool_use, emit tool_results separately.
        text_chunks: list[str] = []
        tool_calls: list[ProviderToolCall] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "text":
                text_chunks.append(block.get("text", ""))
            elif block_type == "tool_use":
                tool_calls.append(
                    ProviderToolCall(
                        id=block.get("id", ""),
                        name=block.get("name", ""),
                        arguments=json.dumps(block.get("input", {})),
                    )
                )
            elif block_type == "tool_result":
                # Emit as a separate 'tool' role message — provider expects
                # tool results in their own message slot, not nested in user content.
                result_content = block.get("content", "")
                if isinstance(result_content, list):
                    # Collapse list-of-blocks to plain text for v1.
                    result_content = "".join(
                        b.get("text", "") if isinstance(b, dict) else str(b) for b in result_content
                    )
                out.append(
                    ProviderMessage(
                        role="tool",
                        content=str(result_content),
                        tool_call_id=block.get("tool_use_id", ""),
                    )
                )

        # Emit the main message with collected text + tool_calls.
        if text_chunks or tool_calls:
            out.append(
                ProviderMessage(
                    role=role,
                    content="".join(text_chunks) or None,
                    tool_calls=tool_calls or None,
                )
            )

    return out


# ============================================================================
# Tool schema construction (agent Tools → JSON Schema dicts)
# ============================================================================


def _build_tools_dict(tools: Tools) -> list[dict] | None:
    """
    Convert agent Tools → list of dict tool schemas for the provider.

    Provider's mapper takes generic dicts with name/description/parameters and
    converts to provider-specific tool format (Anthropic / OpenAI / Gemini).
    """
    if tools is None or len(tools) == 0:
        return None

    out: list[dict] = []
    for tool in tools:
        schema = tool.input_json_schema() or {"type": "object", "properties": {}}
        out.append(
            {
                "name": tool.name,
                "description": getattr(tool, "description_text", "") or "",
                "parameters": schema,
            }
        )
    return out


# ============================================================================
# query_model_with_streaming — the main entrypoint wired into deps.callModel
# ============================================================================


async def query_model_with_streaming(
    messages: list,
    tools: Tools | None = None,
    model: str = "",
    system_prompt: str | None = None,
    **_kwargs: Any,
) -> AsyncIterator[Any]:
    """
    Stream a model response via the existing ProviderAdapter.

    Accumulates text and tool_use blocks from stream events, then emits a
    synthetic assistant message when the adapter signals done. All stream
    events are also forwarded so the router can relay them to the frontend.
    """
    thinking = _kwargs.get("thinking", False)
    adapter = resolve_provider(model)

    request = ChatRequest(
        model=model,
        messages=_normalize_messages_for_api(messages),
        tools=_build_tools_dict(tools) if tools else None,
        thinking=thinking,
    )

    text_parts: list[str] = []
    tool_use_blocks: list[dict] = []
    pending_tool_args: dict[str, list[str]] = {}

    async for event in adapter.stream(request, system_prompt or ""):
        etype = event.event

        if etype == "text_delta":
            text_parts.append(event.data.get("text", ""))
            yield {"type": "text_delta", **event.data}

        elif etype == "tool_call_start":
            call_id = event.data.get("call_id", "")
            name = event.data.get("name", "")
            pending_tool_args[call_id] = []
            yield {"type": "tool_call_start", **event.data}

        elif etype == "tool_call_delta":
            call_id = event.data.get("call_id", "")
            if call_id in pending_tool_args:
                pending_tool_args[call_id].append(event.data.get("delta", ""))

        elif etype == "tool_call_done":
            call_id = event.data.get("call_id", "")
            name = event.data.get("name", "")
            raw_args = event.data.get("arguments", "")
            try:
                parsed_input = json.loads(raw_args) if raw_args else {}
            except json.JSONDecodeError:
                parsed_input = {}
            tool_use_blocks.append(
                {
                    "type": "tool_use",
                    "id": call_id,
                    "name": name,
                    "input": parsed_input,
                }
            )
            pending_tool_args.pop(call_id, None)
            yield {"type": "tool_call_done", **event.data}

        elif etype == "done":
            content: list[dict[str, Any]] = []
            full_text = "".join(text_parts)
            if full_text:
                content.append({"type": "text", "text": full_text})
            content.extend(tool_use_blocks)

            if content:
                yield {
                    "type": "assistant",
                    "message": {"role": "assistant", "content": content},
                }
            yield {"type": "done", **event.data}

        else:
            yield {"type": etype, **event.data}
