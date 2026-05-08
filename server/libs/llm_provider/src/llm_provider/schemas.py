"""Provider-agnostic request / message / event schemas.

These types form the boundary between application code and the OpenAI SDK.
Callers construct :class:`ChatRequest` from their own domain objects, and
the adapter translates them into SDK-specific types via
:mod:`llm_provider.mappers`. Keeping this translation layer thin lets us
swap the underlying client without touching the rest of the codebase.
"""

from pydantic import BaseModel


class ImageData(BaseModel):
    """Inline image payload attached to a user message.

    Stored as base64 rather than a URL so message history is self-contained
    and replayable without depending on external storage still being
    reachable.
    """

    mime_type: str
    base64: str


class ToolCallData(BaseModel):
    """A single tool/function call produced by the assistant.

    ``arguments`` is kept as a raw JSON string rather than a dict because
    the LLM streams them character-by-character; parsing is deferred to the
    caller so partial arguments can be surfaced to the UI progressively.
    """

    id: str
    name: str
    arguments: str


class Message(BaseModel):
    """One turn of a chat conversation.

    Shape intentionally matches the three OpenAI roles we support. ``content``
    is optional because assistant turns can consist solely of tool calls, and
    tool turns carry the call id they're answering in ``tool_call_id``.
    """

    role: str  # "user" | "assistant" | "tool"
    content: str | None = None
    images: list[ImageData] | None = None
    tool_calls: list[ToolCallData] | None = None
    tool_call_id: str | None = None  # for role="tool"


class ChatRequest(BaseModel):
    """Input envelope for :meth:`LLMAdapter.stream` / ``complete`` / ``generate``.

    Attributes:
        model: Provider model id (e.g. ``"claude-opus-4-7"``).
        messages: Conversation turns, oldest first.
        tools: Optional function/tool definitions. Non-``function`` types
            (e.g. ``web_search_preview``) are passed through to the provider
            untouched; see :func:`llm_provider.mappers.build_tools`.
        thinking: Enable reasoning/thinking output. When ``True`` the adapter
            requests reasoning summaries and emits ``thinking_delta`` events.
    """

    model: str
    messages: list[Message]
    tools: list[dict] | None = None
    thinking: bool = False


class StreamEvent:
    """Normalised streaming event emitted by :meth:`LLMAdapter.stream`.

    Provider-specific SDK events are mapped into a small stable set of
    names (``text_delta``, ``thinking_delta``, ``tool_call_start``,
    ``tool_call_delta``, ``tool_call_done``, ``web_search_*``, ``error``,
    ``done``). Consumers should treat unknown event names as no-ops so new
    event types can be added without breaking them.

    Not a Pydantic model on purpose: events are produced in a hot loop and
    :class:`BaseModel` validation is measurable overhead there.
    """

    def __init__(self, event: str, data: dict):
        self.event = event
        self.data = data
