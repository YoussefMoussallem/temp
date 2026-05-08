"""
WebFetchTool helpers — fetch + HTML→text conversion.

Port of src/tools/WebFetchTool/utils.ts (530 lines in source) — minimal v1.

DEFERRED for later phases:
  - 15-minute self-cleaning cache (Phase 5)
  - Binary content detection + disk persistence (Phase 5)
  - Cross-host redirect detection (Phase 5)
  - LLM-based extraction via secondary model (Phase 5)
  - Proper HTML→markdown via html2text/markdownify (Phase 5)

v1 uses BeautifulSoup4 for robust HTML parsing → plain text.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any

import httpx
from bs4 import BeautifulSoup

# Truncation cap for the returned content.
# Source uses MAX_MARKDOWN_LENGTH ~= 150_000; mirroring here.
MAX_MARKDOWN_LENGTH = 150_000

# httpx fetch timeout per request.
_FETCH_TIMEOUT = 30.0

# Tags whose content we drop entirely.
_DROP_TAGS = ("script", "style", "noscript", "iframe", "object", "embed", "svg")


@dataclass
class FetchedContent:
    """Successful fetch result."""
    content: str
    bytes: int
    code: int
    code_text: str
    content_type: str
    persisted_path: str | None = None
    persisted_size: int | None = None


@dataclass
class RedirectResult:
    """Result when URL redirects to a different host (Phase 5: detection)."""
    type: str
    original_url: str
    redirect_url: str
    status_code: int


# ============================================================================
# HTML → text conversion (BeautifulSoup4)
# ============================================================================


def html_to_text(html: str) -> str:
    """Strip HTML tags via BeautifulSoup; collapse whitespace."""
    if not html:
        return ""
    try:
        soup = BeautifulSoup(html, "html.parser")
        # Drop noise tags (their content is never useful to the LLM).
        for tag_name in _DROP_TAGS:
            for tag in soup.find_all(tag_name):
                tag.decompose()
        # `\n` separator preserves block boundaries; strip cleans whitespace.
        text = soup.get_text(separator="\n", strip=True)
    except Exception:
        # Defensive: return raw with regex tag-strip if bs4 fails on weird input.
        text = re.sub(r"<[^>]+>", "", html)

    # Collapse 3+ newlines to 2 (paragraph spacing without ladder effect).
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Collapse runs of inline whitespace.
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


# ============================================================================
# Fetch
# ============================================================================


async def get_url_markdown_content(
    url: str,
    abort_signal: asyncio.Event | None = None,
) -> FetchedContent | RedirectResult:
    """
    Fetch a URL, return its content as text (HTML stripped to plain text in v1).

    Auto-upgrades http → https.
    """
    fetch_url = url.replace("http://", "https://", 1) if url.startswith("http://") else url

    async with httpx.AsyncClient(
        timeout=_FETCH_TIMEOUT,
        follow_redirects=True,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
    ) as client:
        response = await client.get(fetch_url)

    raw_bytes = response.content
    bytes_len = len(raw_bytes)
    content_type = response.headers.get("content-type", "").split(";")[0].strip()

    if "text/html" in content_type:
        text = html_to_text(response.text)
    else:
        # Return as-is for text/plain, text/markdown, application/json, etc.
        # Binary types (PDF, images) skipped in v1 — Phase 5 adds disk persist.
        text = response.text if "text/" in content_type or "json" in content_type else ""

    # Truncate to the cap.
    if len(text) > MAX_MARKDOWN_LENGTH:
        text = text[:MAX_MARKDOWN_LENGTH] + "\n\n[Content truncated — exceeded MAX_MARKDOWN_LENGTH]"

    return FetchedContent(
        content=text,
        bytes=bytes_len,
        code=response.status_code,
        code_text=response.reason_phrase or "",
        content_type=content_type,
    )


# ============================================================================
# Prompt-driven extraction (Phase 5 wires real secondary model call)
# ============================================================================


async def apply_prompt_to_markdown(
    prompt: str,
    content: str,
    abort_signal: Any | None = None,
    is_non_interactive: bool = False,
    is_preapproved: bool = False,
) -> str:
    """
    v1 stub: returns content + prompt header as-is.
    Phase 5 wires a real Haiku/Sonnet-mini call to extract per the prompt.
    """
    return f"[user prompt: {prompt!r}]\n\n{content}"
