"""DeleteSlide — hard-delete a slide from the active project."""

from __future__ import annotations

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
from .prompt import DELETE_SLIDE_TOOL_NAME, DESCRIPTION


class DeleteSlideInput(BaseModel):
    # AliasChoices: ListSlides returns each slide keyed as ``id``; models
    # routinely echo that back. Accept either name so a naming mismatch
    # doesn't fail the call.
    slide_id: str = Field(
        validation_alias=AliasChoices("slide_id", "id"),
        description="UUID of the slide to delete. Also accepts `id`.",
    )


class DeleteSlideToolImpl(BaseTool[DeleteSlideInput, str]):
    name = DELETE_SLIDE_TOOL_NAME
    inputSchema = DeleteSlideInput
    maxResultSizeChars = 1_000
    description_text = DESCRIPTION

    def is_concurrency_safe(self, input: Any = None) -> bool:
        # Delete now renumbers remaining positions to keep them
        # contiguous (matches reorder's invariant). That renumber is
        # NOT race-safe across parallel deletes within one project:
        # tx A reads positions, tx B reads positions, both shift, the
        # final ordering is undefined. Running deletes serially is
        # the simple correct fix — multi-delete batches are rare
        # enough that the speed cost is negligible. Cross-project
        # parallelism is still possible in principle but the loop's
        # batch is single-project by construction.
        return False

    async def prompt(self, options: dict[str, Any]) -> str:
        return DESCRIPTION

    async def validate_input(self, input: Any, context: ToolUseContext) -> ValidationResult:
        if not context.authorization:
            return ValidationError(message="Missing authorization on tool context.", errorCode=1)
        slide_id = (
            (input.get("slide_id") or input.get("id"))
            if isinstance(input, dict)
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
        slides = await db_client.delete_slide(
            context.authorization or "",
            parsed.slide_id,
        )
        # Emit ``slides_replaced`` (not the bare ``slide_deleted``) so the
        # FE picks up the post-renumber positions on every remaining
        # slide, not just the removal of the deleted one. db-service
        # closes the position gap inside the same transaction as the
        # delete; the response carries the new ordered list.
        return ToolResult(
            data=f"Deleted slide {parsed.slide_id}. Deck now has {len(slides)} slides.",
            events=[{"type": "slides_replaced", "slides": slides}],
        )


DeleteSlideTool = DeleteSlideToolImpl()
