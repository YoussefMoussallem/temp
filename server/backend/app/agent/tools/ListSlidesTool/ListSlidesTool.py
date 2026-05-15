"""ListSlides — read the active project's deck so the model can reference ids."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from app.bridges import db_client

from ...Tool import (
    BaseTool,
    ToolResult,
    ToolUseContext,
    ValidationError,
    ValidationOk,
    ValidationResult,
)
from ...types.hooks import CanUseToolFn
from .prompt import DESCRIPTION, LIST_SLIDES_TOOL_NAME


class ListSlidesInput(BaseModel):
    include_html: bool = Field(
        default=False,
        description=(
            "If true, return each slide's full HTML alongside id/position/title. "
            "Leave false unless you actually need the HTML to edit a slide — "
            "full HTML is expensive in tokens."
        ),
    )


class ListSlidesToolImpl(BaseTool[ListSlidesInput, str]):
    name = LIST_SLIDES_TOOL_NAME
    inputSchema = ListSlidesInput
    # Decks can be large; full-HTML listings can easily exceed the default
    # 2KB cap. Keep generous headroom — the LLM opts into HTML explicitly.
    maxResultSizeChars = 50_000
    description_text = DESCRIPTION

    def is_read_only(self, input: Any = None) -> bool:
        return True

    def is_concurrency_safe(self, input: Any = None) -> bool:
        return True

    async def prompt(self, options: dict[str, Any]) -> str:
        return DESCRIPTION

    async def validate_input(self, input: Any, context: ToolUseContext) -> ValidationResult:
        if not context.project_id:
            return ValidationError(
                message="No active project — cannot list slides without project context.",
                errorCode=1,
            )
        if not context.authorization:
            return ValidationError(
                message="Missing authorization on tool context.",
                errorCode=2,
            )
        return ValidationOk()

    async def call(
        self,
        args: Any,
        context: ToolUseContext,
        can_use_tool: CanUseToolFn,
        parent_message: Any,
        on_progress: Any | None = None,
    ) -> ToolResult[str]:
        parsed: ListSlidesInput = (
            args if isinstance(args, ListSlidesInput) else ListSlidesInput(**args)
        )
        slides = await db_client.list_slides(context.authorization or "", context.project_id or "")
        summary = [
            {
                "id": s["id"],
                "position": s["position"],
                "title": s.get("title"),
                **({"html": s.get("html", "")} if parsed.include_html else {}),
            }
            for s in slides
        ]
        payload = {"count": len(summary), "slides": summary}
        return ToolResult(data=json.dumps(payload))


ListSlidesTool = ListSlidesToolImpl()
