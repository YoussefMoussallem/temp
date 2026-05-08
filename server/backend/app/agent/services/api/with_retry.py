"""
Retry / recovery wrapper for LLM streaming calls.

Source: src/services/api/withRetry.ts (822 lines).

Without source access this is implemented from the plan's prose:

  > "Wraps every LLM call with retry + fallback ladder. Layers (in order,
  >  on failure):
  >    a. Standard retry — exponential backoff on transient errors
  >       (5xx, timeouts, rate limits)
  >    b. maxOutputTokensOverride 64K escalation — if output truncated
  >       mid-tool-use, retry with bumped max_output_tokens
  >    c. Streaming downgrade — if streaming fails, retry as non-streaming
  >    d. Reactive compact on prompt_too_long — call reactive_compact,
  >       retry with compacted messages
  >    e. Final escalation — bubble up after N attempts"

What ships in 3.5 (Edwin scope):
  - (a) Standard retry on ``ProviderConnectionError`` /
    ``ProviderServerError`` / ``ProviderRateLimitError``: exponential
    backoff, capped at ``MAX_BACKOFF_SECS``.
  - (d) Reactive compact on ``ProviderInvalidRequestError`` whose
    message looks like a context-window error: heuristic match on the
    error string. The actual recovery (calling ``reactive_compact``,
    swapping the messages list) happens via the ``on_prompt_too_long``
    hook injected by the loop — keeps this module decoupled from the
    compaction stack.
  - (e) Final exhaustion: raises ``MaxRetriesExceeded`` after
    ``max_attempts`` attempts. Caller surfaces a clean error.

What's NOT shipping in 3.5 (deferred to a future sub-phase):
  - (b) ``maxOutputTokensOverride`` escalation. Detecting "output
    truncated mid-tool-use" needs the assistant message to be
    inspectable AFTER the stream finishes (look for an incomplete
    ``tool_use.input`` JSON), and our adapter doesn't surface that
    signal cleanly today. The hook is wired (``on_output_truncated``)
    but the loop's caller passes ``None``; if/when the adapter learns
    to emit a structured ``stop_reason: length`` event the hook turns
    on by changing one line in the loop.
  - (c) Streaming downgrade. The adapter only ships a streaming path
    today; there's no non-streaming entry point to fall back to. The
    hook is wired (``on_streaming_failure``) but ditto — falls back
    to standard transient retry until/unless the adapter grows a
    non-streaming variant.

# TODO(post-3.5): wire (b) and (c) once the adapter signals are richer.

Restart-safety contract:

  The wrapped call is an async generator that yields stream events.
  Once we've yielded a ``text_delta`` / ``tool_call_*`` / ``thinking_delta``
  to the consumer, retrying would produce duplicate events on the SSE
  wire — the user would see "Hello hello" on a transient blip mid-stream.
  So retry is **only safe before the first content-yielding event**.
  After that, exceptions bubble — the caller (query_loop) terminates
  with ``Terminal(reason="model_error")`` exactly like a non-retried
  error today.
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Awaitable, Callable

from app_logger import get_logger

from llm_provider.exceptions import (
    ProviderConnectionError,
    ProviderError,
    ProviderInvalidRequestError,
    ProviderRateLimitError,
    ProviderServerError,
)

log = get_logger(__name__)


# ── Tunable knobs ──────────────────────────────────────────────────────────


# Total tries before giving up. Plan said "N attempts"; we pick 3 so the
# user-facing latency is bounded — base 0.5s + 1.0s + 2.0s = 3.5s of
# backoff in the worst case, plus the actual call time.
# # TUNE: source-parity unknown.
DEFAULT_MAX_ATTEMPTS = 3

# Initial backoff after attempt 1's failure. Doubled each subsequent
# failure up to ``MAX_BACKOFF_SECS``.
# # TUNE: source-parity unknown.
DEFAULT_BASE_BACKOFF_SECS = 0.5

# Cap on a single backoff slice. Stops a long-running retry from holding
# an /turn HTTP connection open for minutes if the provider is sick.
# # TUNE: source-parity unknown.
MAX_BACKOFF_SECS = 8.0

# Substrings that mark a ``ProviderInvalidRequestError`` as a context-
# window overflow rather than a malformed-request (which is non-
# retryable). Matching is lower-case substring on the exception's str().
# Multiple known phrasings because providers/proxies differ:
#   - OpenAI direct uses "context_length_exceeded"
#   - LiteLLM proxy sometimes wraps as "prompt is too long"
#   - Anthropic-style: "input length and ``max_tokens`` exceed"
#   - Generic: any of {"context_length", "prompt_too_long",
#                       "context_window", "too long"}
_PROMPT_TOO_LONG_HINTS = frozenset({
    "context_length",
    "context length",
    "prompt_too_long",
    "prompt is too long",
    "context_window",
    "context window",
    "input is too long",
    "input length and",
    "exceeds the model",
    "maximum context length",
})


# ── Custom exception ──────────────────────────────────────────────────────


class MaxRetriesExceeded(ProviderError):
    """Raised when the recovery ladder runs out of attempts.

    Subclasses ``ProviderError`` so callers can catch the existing
    provider-error hierarchy without learning a new exception type.
    The ``__cause__`` chain preserves the original failure for
    debugging — the human-facing message in ``str()`` is the
    last-attempt error's message.
    """


# ── Helpers ───────────────────────────────────────────────────────────────


def _is_prompt_too_long(exc: Exception) -> bool:
    """Heuristic match: does this look like a context-window overflow?

    Conservative — only returns True when the exception message
    matches a known phrase. False negatives are fine (we just retry-
    or-fail like before); false positives would mean we run a
    compaction on a malformed-request error, wasting an LLM call.
    """
    if not isinstance(exc, ProviderInvalidRequestError):
        return False
    msg = str(exc).lower()
    return any(hint in msg for hint in _PROMPT_TOO_LONG_HINTS)


def _is_transient(exc: Exception) -> bool:
    """True iff the error is a class we retry blindly with backoff."""
    return isinstance(exc, (
        ProviderConnectionError,
        ProviderServerError,
        ProviderRateLimitError,
        asyncio.TimeoutError,
    ))


def _is_content_event(event: Any) -> bool:
    """True iff ``event`` represents user-visible content the consumer
    has already seen. After such an event we cannot safely retry.
    """
    if not isinstance(event, dict):
        return False
    return event.get("type") in (
        "text_delta",
        "tool_call_start",
        "tool_call_delta",
        "tool_call_done",
        "thinking_delta",
        "assistant",
    )


def _backoff_for_attempt(attempt: int, base: float) -> float:
    """``base * 2^(attempt-1)`` capped at ``MAX_BACKOFF_SECS``.

    ``attempt`` is 1-indexed (the first failure leads to attempt-2,
    so we sleep ``base * 2^0 = base`` before retrying).
    """
    return min(MAX_BACKOFF_SECS, base * (2 ** (attempt - 1)))


# ── Public entrypoint ─────────────────────────────────────────────────────


# Type alias — the factory creates a *fresh* async iterator each call.
# It must be a callable returning an iterator (not the iterator itself)
# because retry needs to start a new stream from scratch.
StreamFactory = Callable[[], AsyncIterator[Any]]


async def with_retry(
    factory: StreamFactory,
    *,
    on_prompt_too_long: Callable[[], Awaitable[bool]] | None = None,
    on_output_truncated: Callable[[], Awaitable[bool]] | None = None,
    on_streaming_failure: Callable[[], Awaitable[bool]] | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    base_backoff_secs: float = DEFAULT_BASE_BACKOFF_SECS,
) -> AsyncIterator[Any]:
    """Wrap an LLM streaming generator with the recovery ladder.

    Args:
      factory: Zero-arg callable that returns a *fresh* async iterator
        of stream events. Called once per attempt — a successful
        attempt invokes it once, a retried attempt invokes it again.
      on_prompt_too_long: Called when a prompt-too-long error is
        detected. Should perform reactive compaction and return True
        to signal "retry is now appropriate". Returning False (or
        being None) escalates the error.
      on_output_truncated: Hook for layer (b) — output truncated mid-
        tool-use. Currently always None from the loop; reserved.
      on_streaming_failure: Hook for layer (c) — streaming downgrade.
        Currently always None from the loop; reserved.
      max_attempts: Total tries before giving up. Default 3.
      base_backoff_secs: Initial backoff after the first failure.

    Yields:
      Every stream event from the successful attempt's generator.

    Raises:
      ``MaxRetriesExceeded`` after exhausting attempts on a retryable
      error class.
      Any non-retryable ``ProviderError`` immediately (auth, not-found,
      malformed-non-context-overflow request).
      Any exception that occurs AFTER content has been yielded (no
      duplicate-events allowed on the SSE wire).
    """
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        has_yielded_content = False
        try:
            async for event in factory():
                if _is_content_event(event):
                    has_yielded_content = True
                yield event
            return
        except Exception as e:  # noqa: BLE001
            last_error = e

            if has_yielded_content:
                # Cannot safely retry — events already on the wire.
                # Surface the original error so the loop terminates
                # cleanly via ``Terminal(reason="model_error")``.
                log.warning(
                    "with_retry: error AFTER content yielded (no retry possible): %s",
                    e,
                )
                raise

            # Layer (d): prompt_too_long -> reactive compact.
            if _is_prompt_too_long(e) and on_prompt_too_long is not None:
                try:
                    recovered = await on_prompt_too_long()
                except Exception as hook_e:  # noqa: BLE001
                    log.exception(
                        "with_retry: on_prompt_too_long hook failed: %s", hook_e,
                    )
                    recovered = False
                if recovered:
                    log.info(
                        "with_retry: prompt_too_long recovered via reactive compact "
                        "(attempt %d/%d)",
                        attempt, max_attempts,
                    )
                    # Don't backoff here — compaction itself was an
                    # LLM call and ate latency; re-attempt immediately.
                    continue
                # Hook declined to recover — non-retryable.
                log.warning(
                    "with_retry: prompt_too_long but reactive compact declined; "
                    "surfacing error",
                )
                raise

            # Layer (a): transient error -> backoff + retry.
            if _is_transient(e):
                if attempt >= max_attempts:
                    log.warning(
                        "with_retry: transient error on final attempt %d: %s",
                        attempt, e,
                    )
                    break
                sleep = _backoff_for_attempt(attempt, base_backoff_secs)
                log.info(
                    "with_retry: transient error attempt %d/%d, backing off %.2fs: %s",
                    attempt, max_attempts, sleep, e,
                )
                await asyncio.sleep(sleep)
                continue

            # Reserved hooks (b)/(c) — always None from the loop today.
            # Left here as the integration point so future enrichments
            # don't need to refactor with_retry's structure.
            if on_output_truncated is not None and await on_output_truncated():
                continue
            if on_streaming_failure is not None and await on_streaming_failure():
                continue

            # Anything else (auth, not-found, generic invalid-request) is
            # non-retryable. Surface immediately.
            log.warning(
                "with_retry: non-retryable error attempt %d: %s", attempt, e,
            )
            raise

    # Loop exhausted on a transient class. Wrap and raise.
    raise MaxRetriesExceeded(
        f"LLM call failed after {max_attempts} attempts: {last_error}",
        provider=getattr(last_error, "provider", "") if isinstance(last_error, ProviderError) else "",
        status_code=getattr(last_error, "status_code", None) if isinstance(last_error, ProviderError) else None,
    ) from last_error


__all__ = [
    "MaxRetriesExceeded",
    "with_retry",
    "DEFAULT_MAX_ATTEMPTS",
    "DEFAULT_BASE_BACKOFF_SECS",
    "MAX_BACKOFF_SECS",
]
