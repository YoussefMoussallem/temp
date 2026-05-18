"""CreateSlide — append or insert a slide into the active project's deck."""

from __future__ import annotations

from typing import Any

from app_logger import get_logger
from pydantic import BaseModel, Field

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
from .prompt import CREATE_SLIDE_TOOL_NAME, DESCRIPTION

log = get_logger(__name__)

# Minimum chars for a believable slide HTML. A real document with
# the structural contract (DOCTYPE + html + body + at least one
# positioned div) is comfortably over this floor; anything shorter
# is either truncated mid-tool-call by the SDK / token budget or a
# placeholder the model intended to fill in later. Either way the
# right move is to reject and surface a clean retry-able error.
_MIN_HTML_CHARS = 200


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
            "UUID of an existing slide to insert after. Omit or null to "
            "insert at the top of the deck. Mutually exclusive with "
            "`position`. Use this for one-off inserts into an existing "
            "deck — the backend shifts later slides down inside a "
            "transaction, so calls with `after_slide_id` run serially."
        ),
    )
    position: int | None = Field(
        default=None,
        description=(
            "Explicit zero-based position for the new slide. Mutually "
            "exclusive with `after_slide_id`. Use this when you're "
            "generating multiple slides in one turn: pre-compute "
            "positions starting from the current deck length so each "
            "create takes a unique slot, then emit all the create "
            "calls in one assistant message — the agent loop will run "
            "them in parallel (significantly faster than the serial "
            "`after_slide_id` path). Do NOT reuse a position of an "
            "existing slide; that produces duplicates the backend "
            "doesn't reject."
        ),
    )


class CreateSlideToolImpl(BaseTool[CreateSlideInput, str]):
    name = CREATE_SLIDE_TOOL_NAME
    inputSchema = CreateSlideInput
    maxResultSizeChars = 2_000
    description_text = DESCRIPTION

    def is_concurrency_safe(self, input: Any = None) -> bool:
        # Two concurrency regimes:
        #
        #   * Explicit ``position`` → bare INSERT, no shift, parallel-safe.
        #     The caller picks positions that don't collide; the loop's
        #     parallel-chunk machinery runs the batch concurrently.
        #
        #   * ``after_slide_id`` (or neither) → transactional shift of
        #     every later slide. Parallel calls would race on positions.
        #     Stay serial.
        #
        # ``is_concurrency_safe`` is called per tool_use with the raw
        # input dict, so this per-input decision works with
        # ``_run_parallel_chunk``'s grouping.
        if isinstance(input, dict):
            return input.get("position") is not None
        return getattr(input, "position", None) is not None

    async def prompt(self, options: dict[str, Any]) -> str:
        return DESCRIPTION

    async def validate_input(self, input: Any, context: ToolUseContext) -> ValidationResult:
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
        if isinstance(input, dict):
            html = input.get("html")
            position = input.get("position")
            after_slide_id = input.get("after_slide_id")
        else:
            html = getattr(input, "html", None)
            position = getattr(input, "position", None)
            after_slide_id = getattr(input, "after_slide_id", None)
        if not html or len(html.strip()) < _MIN_HTML_CHARS:
            # Log the actual payload (truncated) so a recurring issue
            # can be pinpointed — empty-HTML creates in production
            # have surfaced previously when a long parallel batch
            # truncated mid-tool-call. Better to know which call_id
            # this was than to swallow it.
            html_str = html if isinstance(html, str) else ""
            log.warning(
                "CreateSlide rejected empty/short html len=%d preview=%r (other input keys: %r)",
                len(html_str),
                html_str[:120],
                ([k for k in input.keys() if k != "html"] if isinstance(input, dict) else None),
            )
            return ValidationError(
                message=(
                    "`html` is empty or too short to be a real slide "
                    f"(< {_MIN_HTML_CHARS} chars). A complete slide is "
                    "a full <!DOCTYPE html><html>…</html> document with "
                    "the structural contract (960×540 canvas, "
                    "absolute-positioned divs, inline styles). If you "
                    "intended to fill the slide later, do it now — "
                    "don't create a placeholder. Re-emit this call "
                    "with the actual content."
                ),
                errorCode=3,
            )
        if position is not None and after_slide_id is not None:
            return ValidationError(
                message="Provide either `position` or `after_slide_id`, not both.",
                errorCode=4,
            )
        if position is not None and position < 0:
            return ValidationError(
                message="`position` must be >= 0.",
                errorCode=5,
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
        parsed: CreateSlideInput = (
            args if isinstance(args, CreateSlideInput) else CreateSlideInput(**args)
        )
        slide = await slides.create_slide(
            context.authorization or "",
            context.project_id or "",
            html=parsed.html,
            title=parsed.title,
            after_slide_id=parsed.after_slide_id,
            position=parsed.position,
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
