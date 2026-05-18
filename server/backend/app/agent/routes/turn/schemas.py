"""Request schemas for /agent/turn."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ToolResultPayload(BaseModel):
    """Result from a frontend-executed tool, sent back via next /turn."""

    call_id: str
    name: str = ""
    output: str = ""
    success: bool = True


class ImagePayload(BaseModel):
    mime_type: str
    base64: str


class AgentTurnRequest(BaseModel):
    """
    /turn request body.

    Message history is loaded from db-service using ``conversation_id`` — the
    frontend no longer round-trips the message array. ClientState (agent
    todos, plan mode) is still round-tripped (not persisted in this phase).

    Model selection is admin-managed: the main-loop and search models are
    resolved per-turn from ``app_settings`` (db-service) via
    ``app_settings_client.resolve``. The frontend no longer chooses them.
    """

    conversation_id: str
    # Optional this phase — frontend starts sending it when slide tools ship.
    # Slide tools raise a clear error when invoked with project_id unset.
    project_id: str | None = None
    thinking: bool = False
    web_search: bool = True
    agent_state: dict = Field(default_factory=dict)
    user_input: str | None = None
    tool_results: list[ToolResultPayload] | None = None
    images: list[ImagePayload] | None = None
    # Slash-command uuid: when user_input begins with '/', the frontend mints
    # a uuid once at Enter-press and the backend expands the command + emits
    # command_lifecycle (started/completed) SSE events keyed on it.
    command_uuid: str | None = None
