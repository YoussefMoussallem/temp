"""System-prompt API-shape helpers.

Two responsibilities, both adjacent to the prompt-content builders in
:mod:`agent.prompts.builder`:

1. **Structural splitting.** :class:`SystemPromptBlock` +
   :func:`split_sys_prompt_prefix` slice the section array on
   :data:`SYSTEM_PROMPT_DYNAMIC_BOUNDARY` into static-prefix / dynamic-tail
   blocks with cache-scope hints. Port of source's
   ``utils/api.ts:splitSysPromptPrefix``.

2. **Wire-format collapse.** :func:`build_system_prompt_string` flattens
   the sliced blocks into a single string for the OpenAI Responses API's
   ``instructions`` parameter (the current LLM adapter shape). The day a
   provider gains array-shape system-prompt support, a sibling builder
   can return ``[{type: "text", text, cache_control}]`` blocks without
   touching call sites.

Cache-scope vocabulary
----------------------

* ``"global"`` — content stable across the whole conversation; safe to put
  behind a long-lived prompt cache (Anthropic ``cache_control`` ephemeral
  or proxy-side prefix cache).
* ``"session"`` — content stable within a single conversation but not
  cross-conversation. Cache scope shorter than ``"global"``.
* ``None`` — explicitly opt out of caching.

All three are advisory — providers that don't support per-block caching
(today: all of them, via the current adapter) ignore the hint.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .builder import SYSTEM_PROMPT_DYNAMIC_BOUNDARY

CacheScope = Literal["global", "session"] | None


@dataclass(frozen=True)
class SystemPromptBlock:
    """A contiguous chunk of system-prompt text with a caching hint."""
    text: str
    cache_scope: CacheScope


def _join(items: list[str]) -> str:
    """Concatenate non-empty section bodies with double newlines, dropping
    any leftover boundary markers (defensive — boundary should already be
    excluded by the caller's slice).
    """
    return "\n\n".join(
        s for s in items
        if s and s != SYSTEM_PROMPT_DYNAMIC_BOUNDARY
    )


def split_sys_prompt_prefix(
    system_prompt: list[str],
    *,
    skip_global_cache: bool = False,
) -> list[SystemPromptBlock]:
    """Split a system-prompt array on :data:`SYSTEM_PROMPT_DYNAMIC_BOUNDARY`.

    Behavior:

    * Boundary present → 2 blocks: prefix (``cache_scope="global"`` unless
      ``skip_global_cache`` forces it down to ``None``) and tail
      (``cache_scope="session"``).
    * Boundary absent → 1 block, ``cache_scope="session"``. This is the
      conservative default — without an explicit boundary we don't know
      what's stable, so we tag the whole thing as session-only.
    * Empty input or all-empty entries → empty list.

    The boundary marker itself never appears in any returned block's
    ``.text`` — it's a structural delimiter, not content.
    """
    boundary_idx: int | None = None
    for i, s in enumerate(system_prompt):
        if s == SYSTEM_PROMPT_DYNAMIC_BOUNDARY:
            boundary_idx = i
            break

    blocks: list[SystemPromptBlock] = []

    if boundary_idx is None:
        joined = _join(system_prompt)
        if joined:
            blocks.append(SystemPromptBlock(text=joined, cache_scope="session"))
        return blocks

    prefix_text = _join(system_prompt[:boundary_idx])
    if prefix_text:
        blocks.append(
            SystemPromptBlock(
                text=prefix_text,
                cache_scope=None if skip_global_cache else "global",
            ),
        )

    tail_text = _join(system_prompt[boundary_idx + 1:])
    if tail_text:
        blocks.append(SystemPromptBlock(text=tail_text, cache_scope="session"))

    return blocks


def build_system_prompt_string(system_prompt: list[str]) -> str:
    """Collapse the system-prompt array into a single string for the wire.

    The agent builder (:func:`agent.prompts.builder.get_system_prompt`)
    returns a ``list[str]`` of section bodies with a boundary marker
    separating the static prefix from the dynamic tail. The current LLM
    adapter (:mod:`llm_provider.adapter`) targets the OpenAI Responses API,
    whose ``instructions`` parameter is a flat string — so the array gets
    flattened here.

    The boundary marker is dropped during the flatten; sections are joined
    by blank lines so each remains independently parseable in tools that
    inspect the prompt (Langfuse, debug logs).

    The flatten goes through :func:`split_sys_prompt_prefix` rather than a
    direct ``"\\n\\n".join`` so the structural slicing is performed
    consistently — when a future adapter supports per-block caching the
    same call site can return :class:`SystemPromptBlock` lists instead.
    """
    return "\n\n".join(
        block.text for block in split_sys_prompt_prefix(system_prompt)
    )
