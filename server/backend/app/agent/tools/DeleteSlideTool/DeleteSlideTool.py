"""DeleteSlide — hard-delete a slide from the active project."""

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
from .prompt import DELETE_SLIDE_TOOL_NAME, DESCRIPTION


class DeleteSlideInput(BaseModel):
    slide_id: str = Field(description="UUID of the slide to delete.")


class DeleteSlideToolImpl(BaseTool[DeleteSlideInput, str]):
    name = DELETE_SLIDE_TOOL_NAME
    inputSchema = DeleteSlideInput
    maxResultSizeChars = 1_000
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
        slide_id = (
            input.get("slide_id") if isinstance(input, dict)
            else getattr(input, "slide_id", None)
        )
        if not slide_id:
            return ValidationError(message="`slide_id` is required.", errorCode=2)
        return ValidationOk()

    async def call(
        self,
        args: Any,
        context: ToolUseContext,
        can_use_tool: CanUseToolFn,
        parent_message: Any,
        on_progress: Any | None = None,
    ) -> ToolResult[str]:
        parsed: DeleteSlideInput = (
            args if isinstance(args, DeleteSlideInput) else DeleteSlideInput(**args)
        )
        await db_client.delete_slide(context.authorization or "", parsed.slide_id)
        return ToolResult(
            data=f"Deleted slide {parsed.slide_id}.",
            events=[{"type": "slide_deleted", "slide_id": parsed.slide_id}],
        )


DeleteSlideTool = DeleteSlideToolImpl()
