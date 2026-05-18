"""ExportDeckDom — ship slide HTML to the browser for DOM-driven .pptx
export.

Sibling to :mod:`ExportDeckTool`. The two tools share the same overall
shape (read slides → emit a "deck export ready" event → frontend
assembles the .pptx) but differ in *how* each slide becomes a .pptx
slide:

* ``ExportDeck`` runs an LLM per-slide to convert HTML into a pptxgenjs
  JSON spec (fully editable text boxes / shapes / images).
* ``ExportDeckDom`` skips the LLM entirely. The backend just packages
  every slide's raw HTML and ships it to the browser, which mounts
  each slide off-screen and runs ``llm-dom-to-pptx`` against the live
  DOM.

The DOM path is faster, costs no tokens, and respects rendered CSS the
LLM converter can't see — but produces less "fully editable" output.
We keep both available and the system prompt mandates asking the user
which they want before invoking either.

Wire format (frontend handler):
  event: deck_export_dom_ready
  data:  {filename, slide_count, slides: [{id, position, title, html}]}
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app_logger import get_logger
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
from .prompt import DESCRIPTION, EXPORT_DECK_DOM_TOOL_NAME

log = get_logger(__name__)


class ExportDeckDomInput(BaseModel):
    filename: str | None = Field(
        default=None,
        description=(
            "Output filename (with or without .pptx extension). "
            "Defaults to 'presentation-dom.pptx' when omitted."
        ),
    )


class ExportDeckDomOutput(BaseModel):
    filename: str
    slide_count: int


class ExportDeckDomToolImpl(BaseTool[ExportDeckDomInput, ExportDeckDomOutput]):
    name = EXPORT_DECK_DOM_TOOL_NAME
    inputSchema = ExportDeckDomInput
    maxResultSizeChars = 2_000
    searchHint = "export the deck to PowerPoint via DOM rendering"
    description_text = DESCRIPTION

    def is_read_only(self, input: Any = None) -> bool:
        return True

    def is_concurrency_safe(self, input: Any = None) -> bool:
        return False

    async def prompt(self, options: dict[str, Any]) -> str:
        return DESCRIPTION

    def user_facing_name(self, input: Any = None) -> str:
        return "Export to PowerPoint (DOM)"

    async def description(self, input: Any, options: dict) -> str:
        name = (
            input.get("filename") if isinstance(input, dict) else getattr(input, "filename", None)
        )
        return (
            f'Export deck to "{name}" via DOM render'
            if name
            else "Export deck to PowerPoint via DOM render"
        )

    async def validate_input(self, input: Any, context: ToolUseContext) -> ValidationResult:
        if not context.project_id:
            return ValidationError(
                message="No active project — cannot export without project context.",
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
    ) -> ToolResult[ExportDeckDomOutput]:
        parsed: ExportDeckDomInput = (
            args if isinstance(args, ExportDeckDomInput) else ExportDeckDomInput(**args)
        )

        filename = _normalize_filename(parsed.filename)

        if on_progress is not None:
            on_progress({"message": "Reading deck..."})

        slides = await slides.list_slides(
            context.authorization or "",
            context.project_id or "",
        )

        if not slides:
            return ToolResult(
                data=ExportDeckDomOutput(filename=filename, slide_count=0),
            )

        # Frontend expects deck preview order; sort by position so the
        # exported .pptx matches what the user sees in the deck panel.
        slides_sorted = sorted(slides, key=lambda s: s.get("position", 0))
        total = len(slides_sorted)

        # Strip everything except the fields the frontend renderer needs.
        # Slide rows from db-service can carry extra metadata (timestamps,
        # author ids, etc.) that just bloats the SSE payload.
        payload_slides = [
            {
                "id": s.get("id"),
                "position": s.get("position", idx),
                "title": s.get("title") or "",
                "html": s.get("html") or "",
            }
            for idx, s in enumerate(slides_sorted)
        ]

        if on_progress is not None:
            on_progress(
                {
                    "message": f"Sending {total} slides to browser for DOM export...",
                    "current": 0,
                    "total": total,
                }
            )

        return ToolResult(
            data=ExportDeckDomOutput(filename=filename, slide_count=total),
            # `deck_export_dom_ready` flows through router.py's catch-all
            # SSE forwarder; the frontend captures it in streamHandler.js
            # and runs `buildAndDownloadDomPptx` in the browser.
            events=[
                {
                    "type": "deck_export_dom_ready",
                    "filename": filename,
                    "slide_count": total,
                    "slides": payload_slides,
                }
            ],
        )

    def map_tool_result_to_block(self, content: ExportDeckDomOutput, tool_use_id: str) -> dict:
        if content.slide_count == 0:
            text = (
                "No slides to export — the deck is empty. "
                "Create at least one slide before exporting."
            )
        else:
            plural = "s" if content.slide_count != 1 else ""
            text = (
                f"Deck exported to {content.filename} via DOM render "
                f"({content.slide_count} slide{plural}). The .pptx "
                f"download started in the user's browser."
            )
        return {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": text,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_filename(name: str | None) -> str:
    """Trim and ensure a `.pptx` extension; fall back to a sane default.

    Default differs from the LLM-converter path so a user who runs both
    in the same session ends up with two distinguishable files instead
    of overwriting one.
    """
    trimmed = (name or "").strip() or "presentation-dom.pptx"
    if not trimmed.lower().endswith(".pptx"):
        trimmed = f"{trimmed}.pptx"
    return trimmed


ExportDeckDomTool = ExportDeckDomToolImpl()
