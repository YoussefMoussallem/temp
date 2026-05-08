"""llm_provider — provider-agnostic LLM client built on the OpenAI Python SDK.

Wraps :class:`openai.AsyncOpenAI` behind a small normalized schema
(:class:`Message`, :class:`ChatRequest`, :class:`StreamEvent`) so application
code never touches SDK-specific types. Main-loop streaming uses the Responses
API; utility callers may use chat completions where Responses is unavailable.
"""

from llm_provider.adapter import LLMAdapter
from llm_provider.schemas import ChatRequest, Message, StreamEvent, ToolCallData

__all__ = [
    "LLMAdapter",
    "ChatRequest",
    "Message",
    "StreamEvent",
    "ToolCallData",
]
