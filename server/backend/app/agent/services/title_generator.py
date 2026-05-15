"""Conversation auto-title generator.

When the user sends their first message in a freshly-created conversation,
the frontend pings the backend to summarise the prompt into a short
sidebar title (4-6 words, plain English, no quotes). This module owns the
prompt + sanitisation; the FastAPI endpoint that calls it is in
``app.agent.router``.

Why a separate module
---------------------

* Keeps the prompt + sanitisation logic testable without importing the
  whole agent router.
* Makes it easy to call from a future "regenerate title" UI button or a
  background reconciler that retitles the first ~10 conversations of a
  newly-imported account.
* Title generation runs **off** the SSE turn stream — failures here must
  never break the chat. The endpoint catches every exception and returns
  ``None`` so the FE can leave the placeholder ("New chat") in place.

Model choice
------------

Uses the configured ``title_model`` from ``app_settings_client`` (falls back
to ``default_model``). Title generation uses **Chat Completions**
(``LLMAdapter.generate_chat_completion``) instead of the Responses API so
deployments on Azure regions without Responses API support still get auto
titles.
"""

from __future__ import annotations

import re

from app_logger import get_logger

from app.bridges.provider_bridge import get_adapter

log = get_logger(__name__)


# Shape of the prompt-input we keep — anything beyond this is truncated
# before sending to the LLM. The LLM only needs enough context to extract
# a 4-6 word title; sending a 10k-character prompt would waste tokens.
_MAX_INPUT_CHARS = 1_500

# Hard cap on the title we'll accept back from the LLM. The DB column
# itself has no length constraint but the sidebar layout breaks beyond
# ~60 characters; the PATCH endpoint enforces 200 as a hard ceiling.
_MAX_TITLE_CHARS = 60

# Regex hits leading/trailing quote-like punctuation. Models love to
# wrap titles in quotes ("Q4 strategy review") despite being told not to.
_QUOTE_TRIM_RE = re.compile(
    r'^[\s"\u201c\u201d\u2018\u2019\'`]+|[\s"\u201c\u201d\u2018\u2019\'`]+$'
)

# Trailing sentence-final punctuation. Models occasionally add a period
# or exclamation point. Strip those — sidebars never punctuate titles.
_TRAILING_PUNCT_RE = re.compile(r"[.!?,:;]+$")


_SYSTEM_PROMPT = (
    "You generate concise titles for chat conversations. Given a user's "
    "first message in a new conversation, produce a 4-6 word title that "
    "summarizes its topic.\n\n"
    "Rules:\n"
    "- 4 to 6 words. No more, no fewer where possible.\n"
    "- Plain English. Sentence case (capitalize the first word and any "
    "proper nouns; lowercase everything else).\n"
    "- No surrounding quotes. No trailing punctuation.\n"
    "- No leading words like 'Help me' / 'How to' — go straight to the topic.\n"
    "- If the prompt is gibberish or has no clear topic, return exactly "
    "'New chat'.\n\n"
    "Output only the title. No prose, no preamble, no markdown."
)


def _sanitize_title(raw: str) -> str:
    """Trim quotes, trailing punctuation, and length. Returns the empty
    string if nothing usable remains (caller treats empty as "fall back
    to placeholder").
    """
    if not raw:
        return ""
    title = raw.strip()
    # Models sometimes echo the system prompt or wrap output in fences;
    # take only the first non-empty line as a defensive measure.
    for line in title.splitlines():
        line = line.strip()
        if line:
            title = line
            break
    title = _QUOTE_TRIM_RE.sub("", title)
    title = _TRAILING_PUNCT_RE.sub("", title).strip()
    if len(title) > _MAX_TITLE_CHARS:
        # Trim on a word boundary if there's one nearby; otherwise hard cut.
        cut = title[:_MAX_TITLE_CHARS]
        last_space = cut.rfind(" ")
        if last_space > _MAX_TITLE_CHARS * 0.6:
            cut = cut[:last_space]
        title = cut.rstrip()
    return title


def _truncate_prompt(prompt: str) -> str:
    """Cap the prompt length sent to the LLM. We don't need the full
    message — the first ~1500 chars carry more than enough topic signal
    for a 4-6 word title."""
    if len(prompt) <= _MAX_INPUT_CHARS:
        return prompt
    cut = prompt[:_MAX_INPUT_CHARS]
    last_space = cut.rfind(" ")
    if last_space > _MAX_INPUT_CHARS * 0.8:
        cut = cut[:last_space]
    return cut + "…"


async def generate_title(prompt: str, model: str) -> str | None:
    """Return a sanitised title for ``prompt``, or ``None`` on any
    failure.

    Never raises — title generation is best-effort. Caller should leave
    the placeholder title in place when this returns ``None``.
    """
    if not prompt or not prompt.strip():
        return None
    if not model:
        log.warning("generate_title called with no model id; skipping")
        return None

    truncated = _truncate_prompt(prompt.strip())

    try:
        adapter = get_adapter()
        raw = await adapter.generate_chat_completion(
            model=model,
            system_prompt=_SYSTEM_PROMPT,
            user_content=truncated,
        )
    except Exception:
        log.warning("Title generation LLM call failed", exc_info=True)
        return None

    if not raw:
        log.warning("Title generation returned empty content from model")
        return None

    title = _sanitize_title(raw)
    if not title:
        log.warning("Title generation returned empty after sanitisation; raw=%r", raw)
        return None
    return title
