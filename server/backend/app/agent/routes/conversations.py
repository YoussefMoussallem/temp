"""POST /agent/conversations/{id}/generate-title — auto-title for fresh conversations.

Best-effort title generation triggered by the FE right after creating a
fresh conversation. The actual prompt + sanitisation lives in
``services.title_generator``; this endpoint is just the HTTP surface
that wires user authorization, the search-model resolution, and the
subsequent PATCH to db-service into one call.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from app.bridges import app_settings_client, db_client
from app.dependencies import CurrentUser, get_current_user
from app_logger import get_logger

from ..services.title_generator import generate_title

log = get_logger(__name__)

router = APIRouter(tags=["agent"])


class GenerateTitleRequest(BaseModel):
    """Body of POST /agent/conversations/{id}/generate-title.

    ``prompt`` is the user's first message in the conversation. We send
    only the text body — images are ignored for titling.
    """

    prompt: str


class GenerateTitleResponse(BaseModel):
    """Response shape. ``title`` is None when generation failed (any
    reason — LLM error, sanitisation produced empty string, etc.). The
    FE should leave its placeholder ("New chat") in place in that case
    rather than blanking the sidebar entry.
    """

    title: str | None = None


@router.post("/conversations/{conversation_id}/generate-title")
async def generate_conversation_title(
    conversation_id: str,
    body: GenerateTitleRequest,
    authorization: str | None = Header(default=None),
    user: CurrentUser = Depends(get_current_user),  # noqa: ARG001 — auth check via dependency
) -> GenerateTitleResponse:
    """Generate a 4-6 word title from the user's first prompt and PATCH
    the conversation row on db-service.

    Best-effort: every failure path (LLM error, empty title, db-service
    PATCH failure) returns ``{title: None}`` and logs at WARNING. The FE
    falls back to its placeholder in that case. We intentionally don't
    surface a 500 here — title generation is a UX nicety, not a
    correctness requirement.
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization")

    # Resolve the title model — admin-configurable; falls back to the
    # main ``default_model`` if no title-specific override is set. Title
    # generation is short and latency-sensitive, so admins typically
    # point this at a small/fast model (e.g. a 7-8B class) even when
    # the main loop runs a larger one.
    models = await app_settings_client.resolve(authorization)

    title = await generate_title(body.prompt, model=models.title_model)
    if not title:
        return GenerateTitleResponse(title=None)

    try:
        await db_client.update_conversation_title(
            authorization,
            conversation_id,
            title=title,
        )
    except Exception:  # noqa: BLE001
        log.warning(
            "Title PATCH to db-service failed for conversation %s",
            conversation_id,
            exc_info=True,
        )
        # The LLM produced a title but persistence failed. Return None so
        # the FE doesn't optimistically render a value the DB doesn't
        # know about. The FE keeps its placeholder; the next manual
        # rename or a retry will sync.
        return GenerateTitleResponse(title=None)

    return GenerateTitleResponse(title=title)
