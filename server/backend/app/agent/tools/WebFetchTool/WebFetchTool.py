"""
WebFetchTool — backend-only tool that fetches a URL and returns its content.

Port of src/tools/WebFetchTool/WebFetchTool.ts.

v1 flow:
  1. LLM emits tool_use {url, prompt}
  2. Loop calls WebFetchTool.call(args, ctx, can_use_tool, ...)
  3. We validate the URL, check permissions (default-allow + preapproved
     hostlist; Phase 4 wires the full hierarchy)
  4. Fetch via httpx, strip HTML to text via stdlib html.parser
  5. Return Output(bytes, code, code_text, result, duration_ms, url)
  6. Loop appends tool_result message → next iteration

Render methods omitted (chat-ui owns rendering per placement memory).
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from ...Tool import (
    BaseTool,
    ToolResult,
    ToolUseContext,
    ValidationError,
    ValidationOk,
    ValidationResult,
)
from ...types.hooks import CanUseToolFn
from ...types.permissions import (
    PermissionAllowDecision,
    PermissionResult,
    _PermissionDecisionReasonOther,
)
from .preapproved import is_preapproved_host
from .prompt import DESCRIPTION, WEB_FETCH_TOOL_NAME
from .utils import (
    FetchedContent,
    MAX_MARKDOWN_LENGTH,
    RedirectResult,
    apply_prompt_to_markdown,
    get_url_markdown_content,
)


# ============================================================================
# Input / Output schemas
# ============================================================================


class WebFetchInput(BaseModel):
    """Input schema for WebFetchTool."""

    url: str = Field(description="The URL to fetch content from")
    prompt: str = Field(
        default="",
        description="The prompt to run on the fetched content (describes what to extract)",
    )


class WebFetchOutput(BaseModel):
    """Output schema for WebFetchTool."""

    bytes: int = Field(description="Size of the fetched content in bytes")
    code: int = Field(description="HTTP response code")
    code_text: str = Field(description="HTTP response code text")
    result: str = Field(description="Processed result from applying the prompt to the content")
    duration_ms: int = Field(description="Time taken to fetch and process the content")
    url: str = Field(description="The URL that was fetched")


# ============================================================================
# WebFetchTool implementation
# ============================================================================


class WebFetchToolImpl(BaseTool[WebFetchInput, WebFetchOutput]):
    """WebFetchTool — fetch a URL, return its content."""

    name = WEB_FETCH_TOOL_NAME
    inputSchema = WebFetchInput
    # 100K chars → tool result persistence threshold.
    maxResultSizeChars = 100_000
    searchHint = "fetch and extract content from a URL"
    shouldDefer = True
    description_text = DESCRIPTION

    def is_concurrency_safe(self, input: Any = None) -> bool:
        return True

    def is_read_only(self, input: Any = None) -> bool:
        return True

    def to_auto_classifier_input(self, input: Any) -> str:
        if isinstance(input, dict):
            url = input.get("url", "")
            prompt = input.get("prompt", "")
        else:
            url = getattr(input, "url", "")
            prompt = getattr(input, "prompt", "")
        return f"{url}: {prompt}" if prompt else url

    async def description(self, input: Any, options: dict) -> str:
        url = input.get("url", "") if isinstance(input, dict) else getattr(input, "url", "")
        try:
            hostname = urlparse(url).hostname or "this URL"
            return f"Fetch content from {hostname}"
        except Exception:
            return "Fetch content from this URL"

    def user_facing_name(self, input: Any = None) -> str:
        return "Fetch"

    async def prompt(self, options: dict) -> str:
        return (
            "IMPORTANT: WebFetch WILL FAIL for authenticated or private URLs. "
            "Before using this tool, check if the URL points to an authenticated "
            "service (e.g. Google Docs, Confluence, Jira, GitHub). If so, look for "
            "a specialized MCP tool that provides authenticated access.\n"
            f"{DESCRIPTION}"
        )

    async def validate_input(self, input: Any, context: ToolUseContext) -> ValidationResult:
        url = input.get("url", "") if isinstance(input, dict) else getattr(input, "url", "")
        if not url:
            return ValidationError(message="Missing url", errorCode=1)
        try:
            parsed = urlparse(url)
            if not parsed.scheme or not parsed.netloc:
                raise ValueError("incomplete URL")
        except Exception:
            return ValidationError(
                message=f'Error: Invalid URL "{url}". The URL provided could not be parsed.',
                errorCode=1,
            )
        return ValidationOk()

    async def check_permissions(self, input: Any, context: ToolUseContext) -> PermissionResult:
        """
        v1: preapproved-host shortcut + default-allow fallback.
        Phase 4 wires the full 4-level rule hierarchy
        (session/project/managed/default per Q9).
        """
        url = input.get("url", "") if isinstance(input, dict) else getattr(input, "url", "")
        try:
            parsed = urlparse(url)
            if is_preapproved_host(parsed.hostname or "", parsed.path or ""):
                return PermissionAllowDecision(
                    behavior="allow",
                    updatedInput=input if isinstance(input, dict) else input.model_dump(),
                    decisionReason=_PermissionDecisionReasonOther(
                        type="other", reason="Preapproved host"
                    ),
                )
        except Exception:
            pass

        # Default-allow until Phase 4 wires the full hierarchy.
        return PermissionAllowDecision(behavior="allow")

    async def call(
        self,
        args: Any,
        context: ToolUseContext,
        can_use_tool: CanUseToolFn,
        parent_message: Any,
        on_progress: Any | None = None,
    ) -> ToolResult[WebFetchOutput]:
        # Coerce to pydantic model if dict.
        parsed: WebFetchInput = args if isinstance(args, WebFetchInput) else WebFetchInput(**args)
        url = parsed.url
        prompt_text = parsed.prompt

        start = int(time.time() * 1000)
        response = await get_url_markdown_content(url)

        if isinstance(response, RedirectResult):
            # Phase 5 implements redirect detection in get_url_markdown_content.
            # Until then this branch is unreachable but kept for parity.
            status_text = {
                301: "Moved Permanently",
                307: "Temporary Redirect",
                308: "Permanent Redirect",
            }.get(response.status_code, "Found")
            message = (
                f"REDIRECT DETECTED: The URL redirects to a different host.\n\n"
                f"Original URL: {response.original_url}\n"
                f"Redirect URL: {response.redirect_url}\n"
                f"Status: {response.status_code} {status_text}\n\n"
                f"To complete your request, fetch the redirect URL with the same prompt."
            )
            output = WebFetchOutput(
                bytes=len(message.encode()),
                code=response.status_code,
                code_text=status_text,
                result=message,
                duration_ms=int(time.time() * 1000) - start,
                url=url,
            )
            return ToolResult(data=output)

        # Successful fetch.
        assert isinstance(response, FetchedContent)
        is_preapproved = False
        try:
            from .preapproved import is_preapproved_url

            is_preapproved = is_preapproved_url(url)
        except Exception:
            pass

        # v1: skip secondary-model extraction if content is small + preapproved
        # markdown; otherwise wrap with the prompt.
        if (
            is_preapproved
            and "text/markdown" in response.content_type
            and len(response.content) < MAX_MARKDOWN_LENGTH
        ):
            result_text = response.content
        else:
            result_text = await apply_prompt_to_markdown(
                prompt_text,
                response.content,
                None,
                context.options.isNonInteractiveSession,
                is_preapproved,
            )

        output = WebFetchOutput(
            bytes=response.bytes,
            code=response.code,
            code_text=response.code_text,
            result=result_text,
            duration_ms=int(time.time() * 1000) - start,
            url=url,
        )
        return ToolResult(data=output)

    def map_tool_result_to_block(self, content: WebFetchOutput, tool_use_id: str) -> dict:
        """The model sees the `result` text as the tool_result content."""
        return {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": content.result if isinstance(content, WebFetchOutput) else str(content),
        }


# Singleton-style instance; mirrors source's `export const WebFetchTool = buildTool({...})`.
WebFetchTool = WebFetchToolImpl()
