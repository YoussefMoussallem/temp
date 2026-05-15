"""LLM adapter: the single entry point for provider calls.

Exposes call shapes built on top of the OpenAI Python SDK:

- :meth:`LLMAdapter.stream` — low-level async iterator of normalised
  :class:`StreamEvent`\\ s. Drives :meth:`openai.AsyncOpenAI.responses.create`
  with ``stream=True``.
- :meth:`LLMAdapter.complete` — wraps :meth:`stream` and collapses text
  deltas into a single ``text`` event while forwarding status/tool events
  live.
- :meth:`LLMAdapter.generate` — non-streaming single-shot call via
  :meth:`openai.AsyncOpenAI.responses.create` (no stream).
- :meth:`LLMAdapter.generate_chat_completion` — non-streaming call via
  :meth:`openai.AsyncOpenAI.chat.completions.create` for simple text
  in/out (e.g. when the Responses API is unavailable on a given Azure
  region).

Every call is wrapped in a Langfuse observation when tracing is configured
and translates SDK exceptions into the provider-agnostic
:mod:`~llm_provider.exceptions` hierarchy at its boundary.
"""

import logging
from collections.abc import AsyncIterator

import openai

from llm_provider.exceptions import (
    ProviderConnectionError,
    classify_status_error,
)
from llm_provider.schemas import ChatRequest, StreamEvent
from llm_provider.mappers import build_input, build_tools
from langfuse_client import generation as langfuse_generation, span as langfuse_span

logger = logging.getLogger(__name__)

_PROVIDER = "openai"

# Generous default: streaming LLM calls with tool use + reasoning can legitimately
# run several minutes end-to-end. Override per-adapter for latency-sensitive paths.
_DEFAULT_TIMEOUT = 600


class LLMAdapter:
    """Async, provider-agnostic LLM client.

    One adapter per (api_key, base_url) pair; typically instantiated once at
    startup and injected wherever LLM access is needed. Safe to share across
    coroutines — the underlying ``AsyncOpenAI`` client handles concurrency.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        *,
        timeout: int = _DEFAULT_TIMEOUT,
        reasoning_effort: str = "medium",
    ):
        """Build the adapter.

        Args:
            api_key: Credential passed straight to the SDK.
            base_url: Provider endpoint. Can point at a proxy (e.g. an
                internal gateway) to rewrite model names or add auth.
            timeout: Per-request timeout in seconds. Streaming calls keep
                the socket open the whole time, so this needs to cover the
                longest plausible response, not just the TTFT.
            reasoning_effort: Default effort level forwarded when
                ``ChatRequest.thinking`` is ``True``. Tuned per deployment.
        """
        self.client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
        )
        self.reasoning_effort = reasoning_effort

    async def stream(self, request: ChatRequest, system_prompt: str) -> AsyncIterator[StreamEvent]:
        """Stream a model response as normalised :class:`StreamEvent`\\ s.

        The Responses API emits many low-level event types; this method
        collapses them into the stable shape the rest of the codebase
        consumes (``text_delta``, ``thinking_delta``, ``tool_call_*``,
        ``web_search_*``, ``error``, ``done``). Unknown event types are
        logged at DEBUG and ignored so SDK upgrades don't break callers.

        The Langfuse context is opened manually (``__enter__`` / ``__exit__``)
        rather than with ``async with`` because generator functions can't
        nest a context manager around a ``yield`` cleanly and still ensure
        it's closed on early termination of the consumer.

        Function-call arguments are streamed as tokens; we track them by
        ``item_id`` (which is opaque and stable within one response) so each
        delta can be attributed to the right logical ``call_id``.
        """
        input_tokens = 0
        output_tokens = 0
        text_parts: list[str] = []
        # item_id -> (call_id, name): item_id is the SDK's transient handle,
        # call_id is the durable identifier the rest of the app references.
        func_calls: dict[str, tuple[str, str]] = {}

        built_tools = build_tools(request.tools)
        kwargs: dict = {
            "model": request.model,
            "instructions": system_prompt,
            "input": build_input(request.messages),
            "stream": True,
        }
        if built_tools:
            kwargs["tools"] = built_tools

        if request.thinking:
            kwargs["reasoning"] = {
                "effort": self.reasoning_effort,
                "summary": "auto",
            }

        trace_input = {k: v for k, v in kwargs.items() if k != "stream"}
        gen_ctx = langfuse_generation("llm-stream", request.model, input_data=trace_input)
        gen_obs = gen_ctx.__enter__() if gen_ctx else None

        try:
            stream = await self.client.responses.create(**kwargs)

            async for event in stream:
                match event.type:
                    case "response.output_text.delta":
                        if event.delta:
                            text_parts.append(event.delta)
                            yield StreamEvent("text_delta", {"text": event.delta})

                    case "response.reasoning_text.delta":
                        if event.delta:
                            yield StreamEvent("thinking_delta", {"text": event.delta})

                    case "response.reasoning_summary_text.delta":
                        # Reasoning summaries stream on a separate channel from
                        # raw reasoning text; both surface to the UI as
                        # "thinking" so the caller doesn't need to care.
                        if event.delta:
                            yield StreamEvent("thinking_delta", {"text": event.delta})

                    case "response.output_item.added":
                        item = event.item
                        if getattr(item, "type", None) == "function_call":
                            item_id = item.id
                            call_id = item.call_id
                            name = item.name
                            func_calls[item_id] = (call_id, name)
                            yield StreamEvent(
                                "tool_call_start",
                                {
                                    "call_id": call_id,
                                    "name": name,
                                },
                            )

                    case "response.function_call_arguments.delta":
                        item_id = event.item_id
                        if event.delta and item_id in func_calls:
                            call_id = func_calls[item_id][0]
                            yield StreamEvent(
                                "tool_call_delta",
                                {
                                    "call_id": call_id,
                                    "delta": event.delta,
                                },
                            )

                    case "response.function_call_arguments.done":
                        item_id = event.item_id
                        if item_id in func_calls:
                            call_id, name = func_calls[item_id]
                            yield StreamEvent(
                                "tool_call_done",
                                {
                                    "call_id": call_id,
                                    "name": name,
                                    "arguments": event.arguments,
                                },
                            )

                    case "response.web_search_call.in_progress":
                        yield StreamEvent("web_search_start", {})

                    case "response.web_search_call.searching":
                        yield StreamEvent("web_search_searching", {})

                    case "response.web_search_call.completed":
                        yield StreamEvent("web_search_done", {})

                    case "response.completed":
                        # Usage is only available on the terminal event;
                        # cache it for the final ``done`` envelope.
                        usage = event.response.usage
                        input_tokens = usage.input_tokens
                        output_tokens = usage.output_tokens

                    case "response.failed":
                        # Provider reported a soft failure mid-stream — surface
                        # the message but don't raise, so partial output is
                        # still preserved for the caller.
                        err = "Unknown error"
                        resp = getattr(event, "response", None)
                        if resp:
                            error_obj = getattr(resp, "error", None)
                            if error_obj:
                                err = getattr(error_obj, "message", str(error_obj))
                        yield StreamEvent("error", {"message": err})

                    case _ if event.type not in (
                        # Known-and-ignored events: emitted by the SDK but
                        # don't map to anything the UI needs to render.
                        "response.created",
                        "response.in_progress",
                        "response.output_item.done",
                        "response.content_part.added",
                        "response.content_part.done",
                        "response.output_text.done",
                        "response.reasoning_text.done",
                        "response.reasoning_summary_text.done",
                        "response.reasoning_summary_part.added",
                        "response.reasoning_summary_part.done",
                        "response.queued",
                    ):
                        logger.debug("Unhandled stream event: %s", event.type)

        except openai.APIStatusError as e:
            if gen_ctx:
                gen_ctx.__exit__(type(e), e, e.__traceback__)
            raise classify_status_error(e.status_code, e.message, _PROVIDER) from e
        except openai.APITimeoutError as e:
            if gen_ctx:
                gen_ctx.__exit__(type(e), e, e.__traceback__)
            raise ProviderConnectionError(
                "Request timed out",
                provider=_PROVIDER,
            ) from e
        except openai.APIConnectionError as e:
            if gen_ctx:
                gen_ctx.__exit__(type(e), e, e.__traceback__)
            raise ProviderConnectionError(str(e), provider=_PROVIDER) from e

        # Success path: record the aggregated output + token usage on the
        # Langfuse observation. Wrapped in try/except because tracing must
        # never take down a successful request.
        if gen_obs:
            try:
                gen_obs.update(
                    output="".join(text_parts),
                    usage_details={
                        "input": input_tokens,
                        "output": output_tokens,
                    },
                )
            except Exception:
                logger.debug("Langfuse generation update failed", exc_info=True)
        if gen_ctx:
            gen_ctx.__exit__(None, None, None)

        yield StreamEvent(
            "done",
            {
                "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
            },
        )

    async def complete(
        self, request: ChatRequest, system_prompt: str
    ) -> AsyncIterator[StreamEvent]:
        """Buffer text deltas, forward everything else live.

        Intended for callers that want tool/search status updates in real
        time but don't care about streaming text character-by-character — e.g.
        background jobs or tests. Yields a single ``text`` event with the
        concatenated output just before the final ``done``.
        """
        text_parts: list[str] = []
        input_tokens = 0
        output_tokens = 0

        span_ctx = langfuse_span(
            "llm-complete",
            request.model,
            input_data={
                "system": system_prompt,
                "messages": build_input(request.messages),
                "tools": build_tools(request.tools),
            },
        )
        span_obs = span_ctx.__enter__() if span_ctx else None

        async for event in self.stream(request, system_prompt):
            if event.event == "text_delta":
                text_parts.append(event.data["text"])
            elif event.event == "done":
                input_tokens = event.data.get("usage", {}).get("input_tokens", 0)
                output_tokens = event.data.get("usage", {}).get("output_tokens", 0)
            else:
                yield event

        if text_parts:
            yield StreamEvent("text", {"text": "".join(text_parts)})

        if span_obs:
            try:
                span_obs.update(
                    output="".join(text_parts),
                    metadata={
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                    },
                )
            except Exception:
                logger.debug("Langfuse complete span update failed", exc_info=True)
        if span_ctx:
            span_ctx.__exit__(None, None, None)

        yield StreamEvent(
            "done",
            {
                "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
            },
        )

    async def generate(self, request: ChatRequest, system_prompt: str = "") -> str:
        """Single non-streaming call — returns the assembled text response.

        Use this when the caller just wants the final answer and doesn't
        care about intermediate events (prompt refinement, summarisation,
        anywhere streaming would add complexity without user value).

        Only the ``output_text`` parts of ``message`` items are concatenated;
        tool calls, reasoning, and other output types are dropped. Callers
        that need those should use :meth:`stream` instead.
        """
        built_tools = build_tools(request.tools)
        kwargs: dict = {
            "model": request.model,
            "instructions": system_prompt,
            "input": build_input(request.messages),
        }
        if built_tools:
            kwargs["tools"] = built_tools
        if request.thinking:
            kwargs["reasoning"] = {
                "effort": self.reasoning_effort,
                "summary": "auto",
            }

        gen_ctx = langfuse_generation("llm-generate", request.model, input_data=dict(kwargs))
        gen_obs = gen_ctx.__enter__() if gen_ctx else None

        try:
            response = await self.client.responses.create(**kwargs)
        except openai.APIStatusError as e:
            if gen_ctx:
                gen_ctx.__exit__(type(e), e, e.__traceback__)
            raise classify_status_error(e.status_code, e.message, _PROVIDER) from e
        except openai.APITimeoutError as e:
            if gen_ctx:
                gen_ctx.__exit__(type(e), e, e.__traceback__)
            raise ProviderConnectionError(
                "Request timed out",
                provider=_PROVIDER,
            ) from e
        except openai.APIConnectionError as e:
            if gen_ctx:
                gen_ctx.__exit__(type(e), e, e.__traceback__)
            raise ProviderConnectionError(str(e), provider=_PROVIDER) from e

        parts: list[str] = []
        for item in response.output:
            if getattr(item, "type", None) == "message":
                for block in item.content:
                    if getattr(block, "type", None) == "output_text":
                        parts.append(block.text)
        result = "".join(parts)

        if gen_obs:
            try:
                usage = getattr(response, "usage", None)
                gen_obs.update(
                    output=result,
                    usage_details={
                        "input": getattr(usage, "input_tokens", 0) if usage else 0,
                        "output": getattr(usage, "output_tokens", 0) if usage else 0,
                    },
                )
            except Exception:
                logger.debug("Langfuse generation update failed", exc_info=True)
        if gen_ctx:
            gen_ctx.__exit__(None, None, None)

        return result

    async def generate_chat_completion(
        self,
        *,
        model: str,
        system_prompt: str,
        user_content: str,
        temperature: float = 0.3,
    ) -> str:
        """Single non-streaming **Chat Completions** call — plain text in/out.

        Use for short utility generations (e.g. chat titles, labels) where
        the Responses API may be unavailable — Azure OpenAI often exposes
        ``chat.completions`` in regions that do not yet enable
        ``responses.create``. Same credentials and ``base_url`` as the rest
        of the adapter; LiteLLM forwards to the appropriate backend.

        Returns the assistant's ``content`` string, or empty string if the
        model returned no text (caller should treat as failure).

        Does **not** support tools or reasoning — only system + user messages.
        """
        kwargs: dict = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": temperature,
        }

        gen_ctx = langfuse_generation(
            "llm-chat-completion",
            model,
            input_data=dict(kwargs),
        )
        gen_obs = gen_ctx.__enter__() if gen_ctx else None

        try:
            response = await self.client.chat.completions.create(**kwargs)
        except openai.APIStatusError as e:
            if gen_ctx:
                gen_ctx.__exit__(type(e), e, e.__traceback__)
            raise classify_status_error(e.status_code, e.message, _PROVIDER) from e
        except openai.APITimeoutError as e:
            if gen_ctx:
                gen_ctx.__exit__(type(e), e, e.__traceback__)
            raise ProviderConnectionError(
                "Request timed out",
                provider=_PROVIDER,
            ) from e
        except openai.APIConnectionError as e:
            if gen_ctx:
                gen_ctx.__exit__(type(e), e, e.__traceback__)
            raise ProviderConnectionError(str(e), provider=_PROVIDER) from e

        choice = response.choices[0] if response.choices else None
        msg = getattr(choice, "message", None) if choice else None
        result = (getattr(msg, "content", None) or "").strip()

        if gen_obs:
            try:
                usage = getattr(response, "usage", None)
                gen_obs.update(
                    output=result,
                    usage_details={
                        "input": getattr(usage, "prompt_tokens", 0) if usage else 0,
                        "output": getattr(usage, "completion_tokens", 0) if usage else 0,
                    },
                )
            except Exception:
                logger.debug("Langfuse generation update failed", exc_info=True)
        if gen_ctx:
            gen_ctx.__exit__(None, None, None)

        return result

    async def list_models(self) -> list[dict]:
        """Fetch available models from the configured endpoint.

        Intended for admin UIs and health checks; returns only the fields we
        actually use (``id``, ``owned_by``) rather than the SDK's full model
        record, which is noisy and version-dependent.
        """
        models = await self.client.models.list()
        return [{"id": m.id, "owned_by": m.owned_by} for m in models.data]
