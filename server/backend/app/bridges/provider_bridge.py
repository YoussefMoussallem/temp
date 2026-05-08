"""LLM provider adapter factory.

Today the backend only talks to one OpenAI-compatible endpoint (our
LiteLLM proxy), so there is exactly one ``LLMAdapter`` and it is
cached. ``resolve_provider(model)`` is the public entry point so that
*callers* pretend there could be more than one - when we add a second
provider (e.g. Anthropic direct), the routing logic lives here and no
caller has to change.

Never instantiate ``LLMAdapter`` directly from outside this module;
always go through ``resolve_provider`` (or ``get_adapter`` if you
genuinely don't care about the model).
"""

from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from llm_provider import LLMAdapter


@lru_cache
def get_adapter() -> LLMAdapter:
    """Return the process-wide LLMAdapter built from current AI settings.

    ``@lru_cache`` on a no-arg function gives us a cheap singleton. If
    settings change at runtime (they don't today) the cache would need
    to be cleared via ``get_adapter.cache_clear()``.
    """
    ai = get_settings().ai
    return LLMAdapter(
        api_key=ai.api_key.get_secret_value(),
        base_url=ai.base_url,
        timeout=ai.stream_timeout,
        reasoning_effort=ai.reasoning_effort,
    )


def resolve_provider(model: str) -> LLMAdapter:
    """Return an LLMAdapter for the given model.

    Currently returns the single configured adapter for all models.
    When multiple providers are needed, this becomes the routing point
    (inspect ``model`` and dispatch to the right adapter instance).
    """
    return get_adapter()
