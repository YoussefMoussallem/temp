"""Memoization framework for dynamic system-prompt sections.

Port of source's ``systemPromptSections.ts``. Each section is a named,
lazily-computed string entry that can be cached across turns within a
process. The cache exists for two reasons:

1. **Stability for proxy-side prefix caching.** Even though the LLM
   adapter currently flattens the system-prompt array into a single
   ``instructions`` string for the OpenAI Responses API, the PwC proxy
   may prefix-cache identical bytes. Recomputing dynamic content (env
   info, memory, etc.) on every turn breaks that cache. Memoizing per
   section means the strings are byte-stable across the whole conversation
   until something explicit invalidates them (``/clear``, compaction).
2. **Cost avoidance.** ``compute`` callbacks may touch disk, Redis, or
   other I/O. Caching avoids re-running them every turn.

Two factories exist:

- :func:`system_prompt_section` — cached. Default for pure functions of
  conversation-stable inputs (env info, memory loaded once per session).
- :func:`DANGEROUS_uncached_system_prompt_section` — bypasses the cache.
  Use only when the section's output legitimately changes between turns
  (e.g. a list of MCP servers that connect/disconnect mid-session). The
  ``reason`` parameter is mandatory and gets logged so opt-outs are
  auditable.

:func:`clear_system_prompt_sections` invalidates the entire cache. Wire
this into ``/clear`` and the auto-compaction path so stale sections never
persist past a context reset.
"""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Union

from app_logger import get_logger

log = get_logger(__name__)

ComputeFn = Callable[[], Union[str, None, Awaitable[Union[str, None]]]]


@dataclass(frozen=True)
class SystemPromptSection:
    """A single named entry in the dynamic-tail of the system prompt.

    ``cache_break`` (when True) signals that this section should NOT be
    memoized — used by :func:`DANGEROUS_uncached_system_prompt_section`.
    Frozen so callers can't accidentally toggle caching mid-resolution.
    """

    name: str
    compute: ComputeFn
    cache_break: bool = False
    reason: str = field(default="")


_section_cache: dict[str, str | None] = {}


def system_prompt_section(name: str, compute: ComputeFn) -> SystemPromptSection:
    """Build a cached section. ``compute`` runs once per process lifetime
    (or until :func:`clear_system_prompt_sections` is called) per ``name``.
    """
    return SystemPromptSection(name=name, compute=compute, cache_break=False)


def DANGEROUS_uncached_system_prompt_section(  # noqa: N802 — name mirrors source for grep parity
    name: str,
    compute: ComputeFn,
    reason: str,
) -> SystemPromptSection:
    """Build an uncached section. ``reason`` is required and logged so the
    opt-out is traceable in audits. Use sparingly — every uncached section
    fragments the prefix-cacheable region of the system prompt.
    """
    if not reason:
        raise ValueError(
            "DANGEROUS_uncached_system_prompt_section requires a reason "
            "explaining why caching is unsafe for this section.",
        )
    return SystemPromptSection(
        name=name,
        compute=compute,
        cache_break=True,
        reason=reason,
    )


async def _invoke(compute: ComputeFn) -> str | None:
    """Call ``compute``, awaiting if it returns a coroutine."""
    out: Any = compute()
    if inspect.isawaitable(out):
        out = await out
    if out is None:
        return None
    if not isinstance(out, str):
        raise TypeError(
            f"system-prompt section compute returned {type(out).__name__}, expected str | None",
        )
    return out


async def resolve_system_prompt_sections(
    sections: list[SystemPromptSection],
) -> list[str]:
    """Resolve every section to its string content, in input order.

    Cached sections check ``_section_cache`` first; uncached sections always
    re-invoke ``compute``. ``None`` results are filtered so callers receive
    only the strings that actually have content. Resolution is sequential —
    if individual sections need parallelism their ``compute`` should manage
    that internally.
    """
    out: list[str] = []
    for s in sections:
        if s.cache_break:
            value = await _invoke(s.compute)
        else:
            if s.name in _section_cache:
                value = _section_cache[s.name]
            else:
                value = await _invoke(s.compute)
                _section_cache[s.name] = value
        if value is not None:
            out.append(value)
    return out


def clear_system_prompt_sections() -> None:
    """Invalidate the section cache.

    Call from ``/clear`` and after autocompaction so dynamic content like
    env info or loaded memory doesn't survive a context reset. Cheap —
    sections recompute lazily on next ``resolve_system_prompt_sections``.
    """
    if _section_cache:
        log.debug("clearing %d cached system-prompt sections", len(_section_cache))
    _section_cache.clear()


def _sync_resolve(sections: list[SystemPromptSection]) -> list[str]:
    """Sync helper sometimes useful in tests / REPL inspection."""
    return asyncio.get_event_loop().run_until_complete(
        resolve_system_prompt_sections(sections),
    )
