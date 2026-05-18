"""POST /agent/export-deck — fire-and-forget deck → editable .pptx (button-driven).

Same conversion pipeline as the ExportDeck agent tool, just without the
agent loop: a frontend button clicks this endpoint directly so the user
doesn't need to chat with the model to download a .pptx.

Streams Server-Sent Events:
  - event: progress, data: {message, current, total}
  - event: deck_export_ready, data: {filename, slide_count, deck}
  - event: error, data: {message}
  - event: done, data: {}

Frontend: see client/app/src/agent/exportDeckClient.js +
components/deck/ExportDeckButton.jsx.
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.bridges import app_settings_client
from app.dependencies import CurrentUser, get_current_user
from app.middleware.rate_limit import limiter, user_or_ip_key
from app_logger import get_logger

from ._shared import _sse

log = get_logger(__name__)

router = APIRouter(tags=["agent"])


class ExportDeckRequest(BaseModel):
    project_id: str
    filename: str | None = None


@router.post("/export-deck")
# Export is heavy (per-slide LLM HTML→pptxgenjs conversion). 20/min/user
# is plenty for normal "export this deck" clicks (most users export
# once or twice in a session) but stops a script driving the export
# endpoint in a tight loop and burning LLM budget.
@limiter.limit("20/minute", key_func=user_or_ip_key)
async def export_deck(
    request: Request,
    body: ExportDeckRequest,
    authorization: str | None = Header(default=None),
    _user: CurrentUser = Depends(get_current_user),
):
    """Run the same per-slide HTML→pptxgenjs conversion as the agent
    tool, but driven by a UI button instead of an LLM tool call.

    The ``_user`` parameter exists so FastAPI runs ``get_current_user``
    (which validates the JWT) — the value itself isn't needed here
    because authorization is forwarded raw to db-service.

    Streams progress + final deck spec as SSE; the browser assembles
    the .pptx from the spec via pptxgenjs."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    return StreamingResponse(
        _stream_export_deck(body, authorization),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


async def _stream_export_deck(
    body: ExportDeckRequest,
    authorization: str,
) -> AsyncIterator[str]:
    """SSE generator: forwards `build_deck_spec`'s on_progress events to
    the wire and emits `deck_export_ready` at the end."""
    from ..tools.ExportDeckTool.ExportDeckTool import build_deck_spec  # noqa: PLC0415

    progress_q: asyncio.Queue[dict] = asyncio.Queue()
    done_sentinel = object()

    def on_progress(p: dict) -> None:
        # build_deck_spec is async, but on_progress is called from inside
        # the event loop, so put_nowait is safe.
        progress_q.put_nowait(p)

    # Admin-managed export model. Falls back to the resolved default
    # model when no export-specific override is set (see
    # ``app_settings_client.resolve``).
    models = await app_settings_client.resolve(authorization)
    convert_model = models.export_model

    async def runner():
        try:
            return await build_deck_spec(
                authorization=authorization,
                project_id=body.project_id,
                filename=body.filename,
                model=convert_model,
                on_progress=on_progress,
            )
        finally:
            progress_q.put_nowait(done_sentinel)  # type: ignore[arg-type]

    task = asyncio.create_task(runner())

    # Drain progress events as they come in. We can't `await task` and
    # `await progress_q.get()` simultaneously without juggling — so we
    # signal completion via the sentinel.
    while True:
        item = await progress_q.get()
        if item is done_sentinel:
            break
        yield _sse("progress", item)

    try:
        deck_spec, total, filename = await task
    except Exception as exc:  # noqa: BLE001
        log.exception("export-deck failed for project=%s: %s", body.project_id, exc)
        yield _sse("error", {"message": str(exc)})
        return

    if total == 0:
        yield _sse("error", {"message": "No slides to export."})
        return

    yield _sse(
        "deck_export_ready",
        {
            "filename": filename,
            "slide_count": total,
            "deck": deck_spec,
        },
    )
    yield _sse("done", {})
