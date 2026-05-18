"""UpdateSlide — overwrite an existing slide's HTML and/or title."""

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
from .prompt import DESCRIPTION, UPDATE_SLIDE_TOOL_NAME


class UpdateSlideInput(BaseModel):
    # AliasChoices: ListSlides returns each slide keyed as ``id`` (the
    # DB-canonical name), and models routinely echo that back when
    # calling UpdateSlide — accept either name so a benign naming
    # mismatch doesn't fail the call. ``slide_id`` stays first so the
    # generated JSON schema still advertises it as the primary field.
    slide_id: str = Field(
        validation_alias=AliasChoices("slide_id", "id"),
        description="UUID of the slide to update. Also accepts `id`.",
    )
    html: str | None = Field(default=None, description="New inner HTML. Omit to keep existing.")
    title: str | None = Field(default=None, description="New title. Omit to keep existing.")


def _coerce_slide_id(input: Any) -> str | None:
    """Pull a slide id out of the raw tool input dict, accepting either
    ``slide_id`` or ``id`` so validate_input's early-fail check stays in
    sync with the AliasChoices in the Pydantic schema."""
    if isinstance(input, dict):
        return input.get("slide_id") or input.get("id")
    return getattr(input, "slide_id", None)


class UpdateSlideToolImpl(BaseTool[UpdateSlideInput, str]):
    name = UPDATE_SLIDE_TOOL_NAME
    inputSchema = UpdateSlideInput
    maxResultSizeChars = 2_000
    description_text = DESCRIPTION

    def is_concurrency_safe(self, input: Any = None) -> bool:
        # Updates on different slide_ids touch independent rows; the
        # cache_del that follows each in db-service is per-project and
        # idempotent, so two parallel updates on the same project just
        # invalidate the cache twice (harmless). Multiple updates in one
        # turn run in parallel via _run_parallel_chunk — events
        # interleave, so the FE sees each slide_updated arrive
        # immediately, not batched at the end.
        return True

    async def prompt(self, options: dict[str, Any]) -> str:
        return DESCRIPTION

    async def validate_input(self, input: Any, context: ToolUseContext) -> ValidationResult:
        if not context.authorization:
            return ValidationError(message="Missing authorization on tool context.", errorCode=1)
        slide_id = _coerce_slide_id(input)
        if isinstance(input, dict):
            html = input.get("html")
            title = input.get("title")
        else:
            html = getattr(input, "html", None)
            title = getattr(input, "title", None)
        if not slide_id:
            return ValidationError(message="`slide_id` is required.", errorCode=2)
        if html is None and title is None:
            return ValidationError(
                message="Provide at least one of `html` or `title`.", errorCode=3
            )
        if html is not None and (not html or len(html.strip()) < 200):
            # Same floor as CreateSlide. A real slide HTML is far
            # longer; anything shorter is either a truncated payload
            # or a placeholder, neither of which should overwrite a
            # real slide's content. ``html is not None`` is the gate:
            # if the caller omitted ``html`` entirely (title-only
            # update), we leave the existing html alone via COALESCE
            # in the SQL.
            return ValidationError(
                message=(
                    "`html` is too short to be a real slide (< 200 chars). "
                    "If you're updating a slide's body, send the full new "
                    "HTML document. If you only want to change the title, "
                    "omit `html` entirely (don't pass an empty string)."
                ),
                errorCode=4,
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
        slide = await slides.update_slide(
            context.authorization or "",
            parsed.slide_id,
            html=parsed.html,
            title=parsed.title,
        )
        changed = [
            k for k, v in {"html": parsed.html, "title": parsed.title}.items() if v is not None
        ]
        return ToolResult(
            data=f"Updated slide {slide['id']} ({', '.join(changed)}).",
            events=[{"type": "slide_updated", "slide": slide}],
        )


UpdateSlideTool = UpdateSlideToolImpl()
