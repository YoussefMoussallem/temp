"""ReorderSlide — move a slide to a new position within its project."""

from __future__ import annotations

from typing import Any

from pydantic import AliasChoices, BaseModel, Field

from app.db import slides

from ...Tool import (
    BaseTool,
    ToolResult,
    ToolUseContext,
    ValidationError,
    ValidationOk,
    ValidationResult,
)
from ...types.hooks import CanUseToolFn
from .prompt import DESCRIPTION, REORDER_SLIDE_TOOL_NAME


class ReorderSlideInput(BaseModel):
    # AliasChoices: ListSlides returns each slide keyed as ``id``; accept
    # either name on the way in so a benign mismatch doesn't fail.
    slide_id: str = Field(
        validation_alias=AliasChoices("slide_id", "id"),
        description="UUID of the slide to move. Also accepts `id`.",
    )
    after_slide_id: str | None = Field(
        default=None,
        description=(
            "UUID of the slide this slide should end up immediately after. "
            "Omit or null to move to the top of the deck."
        ),
    )


class ReorderSlideToolImpl(BaseTool[ReorderSlideInput, str]):
    name = REORDER_SLIDE_TOOL_NAME
    inputSchema = ReorderSlideInput
    maxResultSizeChars = 2_000
    description_text = DESCRIPTION

    async def prompt(self, options: dict[str, Any]) -> str:
        return DESCRIPTION

    async def validate_input(self, input: Any, context: ToolUseContext) -> ValidationResult:
        if not context.authorization:
            return ValidationError(message="Missing authorization on tool context.", errorCode=1)
        if isinstance(input, dict):
            slide_id = input.get("slide_id") or input.get("id")
            after = input.get("after_slide_id")
        else:
            slide_id = getattr(input, "slide_id", None)
            after = getattr(input, "after_slide_id", None)
        if not slide_id:
            return ValidationError(message="`slide_id` is required.", errorCode=2)
        if after == slide_id:
            return ValidationError(message="`after_slide_id` cannot equal `slide_id`.", errorCode=3)
        return ValidationOk()

    async def call(
        self,
        args: Any,
        context: ToolUseContext,
        can_use_tool: CanUseToolFn,
        parent_message: Any,
        on_progress: Any | None = None,
    ) -> ToolResult[str]:
        parsed: ReorderSlideInput = (
            args if isinstance(args, ReorderSlideInput) else ReorderSlideInput(**args)
        )
        slides = await slides.reorder_slide(
            context.authorization or "",
            parsed.slide_id,
            after_slide_id=parsed.after_slide_id,
        )
        return ToolResult(
            data=f"Reordered slide {parsed.slide_id}. Deck now has {len(slides)} slides.",
            events=[{"type": "slides_replaced", "slides": slides}],
        )


ReorderSlideTool = ReorderSlideToolImpl()
