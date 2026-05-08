"""CreateSlide — append or insert a slide into the active project's deck."""

from __future__ import annotations

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
from .prompt import CREATE_SLIDE_TOOL_NAME, DESCRIPTION


class CreateSlideInput(BaseModel):
    html: str = Field(
        description=(
            "Complete standalone HTML document for the slide "
            "(`<!DOCTYPE html><html>…</html>`). See the CreateSlide tool "
            "description for the full structural contract: 960×540 canvas, "
            "absolute-positioned divs, inline styles only, system fonts, "
            "no JavaScript."
        ),
    )
    title: str | None = Field(
        default=None,
        description="Optional short label for the slide (shown in the deck panel).",
    )
    after_slide_id: str | None = Field(
        default=None,
        description=(
            "UUID of an existing slide to insert after. Omit or null to insert at "
            "the top of the deck."
        ),
    )


class CreateSlideToolImpl(BaseTool[CreateSlideInput, str]):
    name = CREATE_SLIDE_TOOL_NAME
    inputSchema = CreateSlideInput
    maxResultSizeChars = 2_000
    description_text = DESCRIPTION

    async def prompt(self, options: dict[str, Any]) -> str:
        return DESCRIPTION

    async def validate_input(
        self, input: Any, context: ToolUseContext
    ) -> ValidationResult:
        if not context.project_id:
            return ValidationError(
                message="No active project — cannot create a slide without project context.",
                errorCode=1,
            )
        if not context.authorization:
            return ValidationError(
                message="Missing authorization on tool context.",
                errorCode=2,
            )
        html = input.get("html") if isinstance(input, dict) else getattr(input, "html", None)
        if not html:
            return ValidationError(message="`html` must not be empty.", errorCode=3)
        return ValidationOk()

    async def call(
        self,
        args: Any,
        context: ToolUseContext,
        can_use_tool: CanUseToolFn,
        parent_message: Any,
        on_progress: Any | None = None,
    ) -> ToolResult[str]:
        parsed: CreateSlideInput = (
            args if isinstance(args, CreateSlideInput) else CreateSlideInput(**args)
        )
        slide = await db_client.create_slide(
            context.authorization or "",
            context.project_id or "",
            html=parsed.html,
            title=parsed.title,
            after_slide_id=parsed.after_slide_id,
        )
        return ToolResult(
            data=(
                f"Created slide {slide['id']} at position {slide['position']}"
                + (f" (title: {slide['title']})" if slide.get("title") else "")
                + "."
            ),
            events=[{"type": "slide_created", "slide": slide}],
        )


CreateSlideTool = CreateSlideToolImpl()
