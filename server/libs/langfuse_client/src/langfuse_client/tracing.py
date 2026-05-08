"""Langfuse observation context-manager helpers.

Thin wrappers around :meth:`Langfuse.start_as_current_observation` that
return ``None`` when tracing is disabled, so callers can write branch-free
code::

    ctx = generation("chat.completion", model="claude-opus-4-7")
    if ctx:
        with ctx as obs:
            obs.update(output=...)

Returning ``None`` instead of raising means services can be run without
Langfuse credentials (local dev, tests, CI) without sprinkling
try/except or feature flags through the call sites.
"""

from __future__ import annotations

from langfuse_client.client import get_client

__all__ = ["generation", "span"]


def generation(name: str, model: str, input_data: dict | None = None):
    """Return a Langfuse *generation* observation context manager, or ``None``.

    Use for LLM calls: the ``generation`` observation type carries the model
    name and input/output fields that Langfuse's UI expects for token
    accounting and cost breakdowns.

    Args:
        name: Human-readable observation label (e.g. ``"chat.completion"``).
        model: Provider model id (e.g. ``"claude-opus-4-7"``). Used by
            Langfuse for cost/latency dashboards.
        input_data: Optional structured input (messages, tools, params).

    Returns:
        A context manager from the Langfuse SDK, or ``None`` when the client
        is not initialised — callers should guard with ``if ctx:`` before
        using ``with``.
    """
    lf = get_client()
    if lf is None:
        return None
    return lf.start_as_current_observation(
        as_type="generation",
        name=name,
        model=model,
        input=input_data,
    )


def span(name: str, model: str, input_data: dict | None = None):
    """Return a Langfuse *span* observation context manager, or ``None``.

    Use for non-LLM work you still want to trace — tool execution, retrieval,
    orchestration steps. ``model`` is folded into ``input`` because the
    ``span`` observation type has no first-class ``model`` field; keeping it
    in the input payload preserves the association in the Langfuse UI.
    """
    lf = get_client()
    if lf is None:
        return None
    payload: dict = {"model": model}
    if input_data:
        payload.update(input_data)
    return lf.start_as_current_observation(
        as_type="span",
        name=name,
        input=payload,
    )
