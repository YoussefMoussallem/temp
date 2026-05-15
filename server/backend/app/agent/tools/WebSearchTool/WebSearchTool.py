"""
WebSearchTool — searches the web via a secondary model with web_search_preview.

Uses the LLM provider adapter to call a search-capable model, collects the
streamed text result, and returns it as the tool output.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app_logger import get_logger
from app.bridges import app_settings_client
from app.bridges.provider_bridge import get_adapter

from ...Tool import (
    BaseTool,
    ToolResult,
    ToolUseContext,
    ValidationError,
    ValidationOk,
    ValidationResult,
)
from ...types.hooks import CanUseToolFn
from .prompt import DESCRIPTION, WEB_SEARCH_TOOL_NAME

log = get_logger(__name__)


class WebSearchInput(BaseModel):
    query: str = Field(description="The search query")


class WebSearchOutput(BaseModel):
    query: str = Field(description="The original search query")
    result: str = Field(description="Search result text")


class WebSearchToolImpl(BaseTool[WebSearchInput, WebSearchOutput]):
    """WebSearchTool — search the web via a search-capable model."""

    name = WEB_SEARCH_TOOL_NAME
    inputSchema = WebSearchInput
    maxResultSizeChars = 100_000
    searchHint = "search the web for current information"
    shouldDefer = True
    description_text = DESCRIPTION

    def is_concurrency_safe(self, input: Any = None) -> bool:
        return True

    def is_read_only(self, input: Any = None) -> bool:
        return True

    async def description(self, input: Any, options: dict) -> str:
        q = input.get("query", "") if isinstance(input, dict) else getattr(input, "query", "")
        return f'Search the web for "{q[:60]}"' if q else "Search the web"

    def user_facing_name(self, input: Any = None) -> str:
        return "Web Search"

    async def prompt(self, options: dict[str, Any]) -> str:
        return DESCRIPTION

    async def validate_input(self, input: Any, context: ToolUseContext) -> ValidationResult:
        q = input.get("query", "") if isinstance(input, dict) else getattr(input, "query", "")
        if not q or not q.strip():
            return ValidationError(message="Missing or empty query", errorCode=1)
        return ValidationOk()

    async def call(
        self,
        args: Any,
        context: ToolUseContext,
        can_use_tool: CanUseToolFn,
        parent_message: Any,
        on_progress: Any | None = None,
    ) -> ToolResult[WebSearchOutput]:
        from llm_provider import ChatRequest, Message  # noqa: PLC0415

        parsed: WebSearchInput = (
            args if isinstance(args, WebSearchInput) else WebSearchInput(**args)
        )

        # Prefer the model the agent loop is already configured with
        # (resolved per-turn from app_settings + admin defaults). Fall
        # back to a fresh resolve only when the loop didn't set one
        # (e.g. tool invoked outside the standard /turn pipeline).
        search_model = context.options.searchModel
        if not search_model:
            resolved = await app_settings_client.resolve(context.authorization or "")
            search_model = resolved.search_model
        if not search_model:
            search_model = context.options.mainLoopModel

        adapter = get_adapter()

        thinking = True
        parts: list[str] = []

        # Emit progress roughly every ~500 chars of streamed response. For a
        # typical 3-10s WebSearch run producing a few KB of text this lands
        # an event every couple of seconds — enough to show the tool is
        # alive without flooding the SSE stream.
        _PROGRESS_EVERY_CHARS = 500

        for attempt in range(2):
            request = ChatRequest(
                model=search_model,
                messages=[Message(role="user", content=parsed.query)],
                tools=[{"type": "web_search_preview"}],
                thinking=thinking,
            )
            parts.clear()
            if on_progress is not None:
                on_progress({"message": f'Searching the web for "{parsed.query[:60]}"...'})
            char_count = 0
            last_progress_at = 0
            try:
                async for ev in adapter.stream(request, ""):
                    if ev.event in ("text_delta", "text"):
                        text = ev.data.get("text", "")
                        parts.append(text)
                        char_count += len(text)
                        if (
                            on_progress is not None
                            and char_count - last_progress_at >= _PROGRESS_EVERY_CHARS
                        ):
                            on_progress({"message": f"Receiving results ({char_count} chars)"})
                            last_progress_at = char_count
                break
            except Exception:
                if attempt == 0 and thinking:
                    log.debug("Search with thinking failed, retrying without")
                    thinking = False
                else:
                    raise

        result_text = "".join(parts) or "[no search results returned]"

        output = WebSearchOutput(query=parsed.query, result=result_text)
        return ToolResult(data=output)

    def map_tool_result_to_block(self, content: WebSearchOutput, tool_use_id: str) -> dict:
        return {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": content.result if isinstance(content, WebSearchOutput) else str(content),
        }


WebSearchTool = WebSearchToolImpl()
