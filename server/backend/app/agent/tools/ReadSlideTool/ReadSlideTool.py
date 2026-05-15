"""ReadSlide — fetch one slide's full content (id, position, title, html)."""

from __future__ import annotations

import json
from typing import Any

from pydantic import AliasChoices, BaseModel, Field

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
from .prompt import DESCRIPTION, READ_SLIDE_TOOL_NAME


class ReadSlideInput(BaseModel):
    # AliasChoices: ListSlides returns each slide keyed as ``id``; the
    # model routinely echoes that back when calling ReadSlide, so accept
    # either name.
    slide_id: str = Field(
        validation_alias=AliasChoices("slide_id", "id"),
        description=(
            "UUID of the slide to read. Also accepts `id`. Obtain it "
            "from `ListSlides` (no html) or from earlier conversation "
            "context."
        ),
    )


class ReadSlideToolImpl(BaseTool[ReadSlideInput, str]):
    name = READ_SLIDE_TOOL_NAME
    inputSchema = ReadSlideInput
    # One slide's HTML is comfortably under this cap; mirrors ListSlides'
    # headroom so a slide with rich inline assets doesn't trip the budget.
    maxResultSizeChars = 50_000
    description_text = DESCRIPTION

    def is_read_only(self, input: Any = None) -> bool:
        return True

    def is_concurrency_safe(self, input: Any = None) -> bool:
        return True

    async def prompt(self, options: dict[str, Any]) -> str:
        return DESCRIPTION

    async def validate_input(
        self,
        input: Any,
        context: ToolUseContext,
    ) -> ValidationResult:
        if not context.authorization:
            return ValidationError(
                message="Missing authorization on tool context.",
                errorCode=1,
            )
        slide_id = (
            (input.get("slide_id") or input.get("id"))
            if isinstance(input, dict)
            else getattr(input, "slide_id", None)
        )
        if not slide_id:
            return ValidationError(
                message="slide_id is required.",
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
        parsed: ReadSlideInput = (
            args if isinstance(args, ReadSlideInput) else ReadSlideInput(**args)
        )

        slide = await db_client.get_slide(
            context.authorization or "",
            parsed.slide_id,
        )
        if slide is None:
            # Soft error — the loop wraps it as an is_error tool_result so
            # the model can recover by listing the deck and picking a real
            # id.
            raise ValueError(
                f"No slide with id={parsed.slide_id}. Use ListSlides to see what exists."
            )

        payload = {
            "id": slide.get("id"),
            "position": slide.get("position"),
            "title": slide.get("title"),
            "html": slide.get("html", ""),
        }
        return ToolResult(data=json.dumps(payload))


ReadSlideTool = ReadSlideToolImpl()
