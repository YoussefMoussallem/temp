"""ExportDeck — convert each slide's HTML to a pptxgenjs JSON spec via LLM
and stream the assembled deck spec to the browser for client-side .pptx
assembly.

Flow:
  1. List all slides from db-service.
  2. For every slide, call LLMAdapter.generate(...) with the converter
     system prompt — converts the HTML into a small JSON spec describing
     pptxgenjs primitives (text boxes / shapes / images).
  3. Emit per-slide on_progress events so the chat UI shows
     "Converting slide N of M".
  4. Return a ToolResult with a `deck_export_ready` event carrying the
     full deck spec (filename + per-slide specs). The agent router's
     catch-all SSE forwarder passes that event through to the browser,
     where useChat picks it up and runs pptxgenjs.

Why backend-driven instead of an interactive UI: the user asked for a
"fully agentic" experience — once the model decides to export, the
browser should download the .pptx without an extra click. Backend-side
LLM conversion also keeps the converter model choice and prompt
centralized (vs. asking each browser to call the LLM itself).
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from pydantic import BaseModel, Field

from app_logger import get_logger
from app.bridges import app_settings_client, db_client
from app.bridges.provider_bridge import get_adapter

from ...Tool import (
    BaseTool,
    ToolResult,
    ToolUseContext,
    ValidationError,
    ValidationOk,
    ValidationResult,
)
from ...types.hooks import CanUseToolFn
from .prompt import CONVERTER_SYSTEM_PROMPT, DESCRIPTION, EXPORT_DECK_TOOL_NAME

log = get_logger(__name__)


# Cap concurrent per-slide LLM calls. Decks of 20+ slides would otherwise
# fan out to 20+ concurrent calls and trip provider rate limits.
_MAX_CONCURRENT_CONVERSIONS = 4

# Strip ```json ... ``` (or bare ```) fences if the model adds them despite
# the prompt telling it not to. We don't trust the LLM to obey "no fences"
# 100% of the time, and an unparseable JSON would abort the whole export.
_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


class ExportDeckInput(BaseModel):
    filename: str | None = Field(
        default=None,
        description=(
            "Output filename (with or without .pptx extension). "
            "Defaults to 'presentation.pptx' when omitted."
        ),
    )


class ExportDeckOutput(BaseModel):
    filename: str
    slide_count: int


class ExportDeckToolImpl(BaseTool[ExportDeckInput, ExportDeckOutput]):
    name = EXPORT_DECK_TOOL_NAME
    inputSchema = ExportDeckInput
    maxResultSizeChars = 2_000
    searchHint = "export the deck to an editable PowerPoint .pptx file"
    description_text = DESCRIPTION

    def is_read_only(self, input: Any = None) -> bool:
        return True

    def is_concurrency_safe(self, input: Any = None) -> bool:
        return False

    async def prompt(self, options: dict[str, Any]) -> str:
        return DESCRIPTION

    def user_facing_name(self, input: Any = None) -> str:
        return "Export to PowerPoint"

    async def description(self, input: Any, options: dict) -> str:
        name = (
            input.get("filename")
            if isinstance(input, dict)
            else getattr(input, "filename", None)
        )
        return f'Export deck to "{name}"' if name else "Export deck to PowerPoint"

    async def validate_input(
        self, input: Any, context: ToolUseContext
    ) -> ValidationResult:
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
    ) -> ToolResult[ExportDeckOutput]:
        parsed: ExportDeckInput = (
            args if isinstance(args, ExportDeckInput) else ExportDeckInput(**args)
        )
        # Use the admin-managed export model for conversion. Slide HTML
        # is short and the JSON shape is constrained, so a smaller
        # model is fine — the admin can dial it up or down. Falls
        # back to the resolved default model when no export-specific
        # override is set (see ``app_settings_client.resolve``).
        models = await app_settings_client.resolve(context.authorization or "")
        convert_model = models.export_model

        deck_spec, total, filename = await build_deck_spec(
            authorization=context.authorization or "",
            project_id=context.project_id or "",
            filename=parsed.filename,
            model=convert_model,
            on_progress=on_progress,
        )

        if total == 0:
            return ToolResult(
                data=ExportDeckOutput(filename=filename, slide_count=0),
            )

        return ToolResult(
            data=ExportDeckOutput(filename=filename, slide_count=total),
            # `deck_export_ready` flows through router.py's catch-all SSE
            # forwarder; the frontend captures it in streamHandler.js and
            # builds the .pptx in the browser.
            events=[{
                "type": "deck_export_ready",
                "filename": filename,
                "slide_count": total,
                "deck": deck_spec,
            }],
        )

    def map_tool_result_to_block(
        self, content: ExportDeckOutput, tool_use_id: str
    ) -> dict:
        if content.slide_count == 0:
            text = (
                "No slides to export — the deck is empty. "
                "Create at least one slide before exporting."
            )
        else:
            plural = "s" if content.slide_count != 1 else ""
            text = (
                f"Deck exported to {content.filename} "
                f"({content.slide_count} slide{plural}). The .pptx download "
                f"started in the user's browser."
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
    """Trim and ensure a `.pptx` extension; fall back to a sane default."""
    trimmed = (name or "").strip() or "presentation.pptx"
    if not trimmed.lower().endswith(".pptx"):
        trimmed = f"{trimmed}.pptx"
    return trimmed


async def _convert_slide_html(
    adapter: Any,
    chat_request_cls: Any,
    message_cls: Any,
    model: str,
    html: str,
) -> dict:
    """Ask the LLM to turn one slide's HTML into a pptxgenjs JSON spec."""
    request = chat_request_cls(
        model=model,
        messages=[message_cls(role="user", content=html)],
        thinking=False,
    )
    raw = await adapter.generate(request, CONVERTER_SYSTEM_PROMPT)
    cleaned = _strip_fences(raw)
    try:
        spec = json.loads(cleaned)
    except json.JSONDecodeError as e:
        # Surface the failure to the caller — the per-slide gather()
        # wraps each conversion in try/except and emits a fallback
        # placeholder, so a single unparseable response doesn't abort
        # the whole deck.
        log.warning("ExportDeck: LLM returned non-JSON spec: %s", raw[:300])
        raise ValueError(f"LLM returned non-JSON spec: {e}") from e

    if not isinstance(spec, dict) or "elements" not in spec:
        raise ValueError(
            "LLM spec missing required 'elements' field"
        )
    return spec


def _strip_fences(text: str) -> str:
    """Remove ```json … ``` fences if present."""
    stripped = text.strip()
    # Fast path: no fences.
    if not stripped.startswith("```"):
        return stripped
    # Regex strips both leading and trailing fence in one go.
    return _FENCE_RE.sub("", stripped).strip()


def _fallback_spec(title: str, error_msg: str) -> dict:
    """Placeholder spec for a slide that failed to convert.

    Emits a basic title + error banner so the user still gets a slide
    in the deck and can identify which one to fix.
    """
    return {
        "background": {"color": "FFFFFF"},
        "elements": [
            {
                "kind": "text",
                "text": title,
                "options": {
                    "x": 0.5, "y": 0.5, "w": 12.33, "h": 1,
                    "fontSize": 32, "bold": True, "color": "1B2A4A",
                    "fontFace": "Arial",
                },
            },
            {
                "kind": "text",
                "text": error_msg,
                "options": {
                    "x": 0.5, "y": 2, "w": 12.33, "h": 4,
                    "fontSize": 16, "color": "9B1B30",
                    "fontFace": "Arial",
                },
            },
        ],
    }


# ---------------------------------------------------------------------------
# Public orchestration helper — used by both the agent tool and the
# user-facing /agent/export-deck endpoint (clicked from the deck panel).
# ---------------------------------------------------------------------------


async def build_deck_spec(
    *,
    authorization: str,
    project_id: str,
    filename: str | None,
    model: str,
    on_progress: Any | None = None,
) -> tuple[dict, int, str]:
    """Read every slide for ``project_id`` and convert each to a pptxgenjs
    JSON spec via LLM.

    Returns ``(deck_spec, slide_count, normalized_filename)``. When the
    project has no slides, returns ``({...}, 0, normalized_filename)`` —
    the empty deck is still valid; callers decide whether to error out.

    ``on_progress`` is a fire-and-forget callback receiving
    ``{"message": str, "current": int, "total": int}`` dicts so callers
    (the agent tool, the deck-button SSE endpoint, etc.) can surface
    per-slide progress to their respective UIs.
    """
    from llm_provider import ChatRequest, Message  # noqa: PLC0415

    final_filename = _normalize_filename(filename)

    if on_progress is not None:
        on_progress({"message": "Reading deck..."})

    slides = await db_client.list_slides(authorization, project_id)
    if not slides:
        empty_spec = {
            "filename": final_filename,
            "layout": "LAYOUT_WIDE",
            "slides": [],
        }
        return empty_spec, 0, final_filename

    # Deck preview shows slides in `position` order; respect that for
    # export so the .pptx matches what the user sees.
    slides_sorted = sorted(slides, key=lambda s: s.get("position", 0))
    total = len(slides_sorted)

    adapter = get_adapter()

    sem = asyncio.Semaphore(_MAX_CONCURRENT_CONVERSIONS)
    completed = {"n": 0}

    if on_progress is not None:
        on_progress({
            "message": f"Converting 0 / {total} slides...",
            "current": 0,
            "total": total,
        })

    async def convert_one(idx: int, slide: dict) -> dict:
        html = slide.get("html") or ""
        async with sem:
            try:
                spec = await _convert_slide_html(
                    adapter, ChatRequest, Message, model, html
                )
            except Exception as e:  # noqa: BLE001
                log.exception(
                    "ExportDeck: slide conversion failed (idx=%d, id=%s)",
                    idx, slide.get("id"),
                )
                spec = _fallback_spec(
                    slide.get("title") or f"Slide {idx + 1}",
                    f"Conversion failed: {e}",
                )

            completed["n"] += 1
            if on_progress is not None:
                on_progress({
                    "message": f"Converting {completed['n']} / {total} slides...",
                    "current": completed["n"],
                    "total": total,
                })

            return {
                "id": slide.get("id"),
                "position": slide.get("position", idx),
                "title": slide.get("title") or "",
                "spec": spec,
            }

    per_slide = await asyncio.gather(
        *(convert_one(i, s) for i, s in enumerate(slides_sorted))
    )

    if on_progress is not None:
        on_progress({"message": "Assembling .pptx...", "current": total, "total": total})

    deck_spec = {
        "filename": final_filename,
        "layout": "LAYOUT_WIDE",
        "slides": per_slide,
    }
    return deck_spec, total, final_filename


ExportDeckTool = ExportDeckToolImpl()
