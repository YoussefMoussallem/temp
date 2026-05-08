"""UpdateSlide — overwrite an existing slide's HTML and/or title."""

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
from .prompt import DESCRIPTION, UPDATE_SLIDE_TOOL_NAME


class UpdateSlideInput(BaseModel):
    slide_id: str = Field(description="UUID of the slide to update.")
    html: str | None = Field(default=None, description="New inner HTML. Omit to keep existing.")
    title: str | None = Field(default=None, description="New title. Omit to keep existing.")


class UpdateSlideToolImpl(BaseTool[UpdateSlideInput, str]):
    name = UPDATE_SLIDE_TOOL_NAME
    inputSchema = UpdateSlideInput
    maxResultSizeChars = 2_000
    description_text = DESCRIPTION

    async def prompt(self, options: dict[str, Any]) -> str:
        return DESCRIPTION

    async def validate_input(
        self, input: Any, context: ToolUseContext
    ) -> ValidationResult:
        if not context.authorization:
            return ValidationError(
                message="Missing authorization on tool context.", errorCode=1
            )
        if isinstance(input, dict):
            slide_id = input.get("slide_id")
            html = input.get("html")
            title = input.get("title")
        else:
            slide_id = getattr(input, "slide_id", None)
            html = getattr(input, "html", None)
            title = getattr(input, "title", None)
        if not slide_id:
            return ValidationError(message="`slide_id` is required.", errorCode=2)
        if html is None and title is None:
            return ValidationError(
                message="Provide at least one of `html` or `title`.", errorCode=3
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
        parsed: UpdateSlideInput = (
            args if isinstance(args, UpdateSlideInput) else UpdateSlideInput(**args)
        )
        slide = await db_client.update_slide(
            context.authorization or "",
            parsed.slide_id,
            html=parsed.html,
            title=parsed.title,
        )
        changed = [k for k, v in {"html": parsed.html, "title": parsed.title}.items() if v is not None]
        return ToolResult(
            data=f"Updated slide {slide['id']} ({', '.join(changed)}).",
            events=[{"type": "slide_updated", "slide": slide}],
        )


UpdateSlideTool = UpdateSlideToolImpl()
