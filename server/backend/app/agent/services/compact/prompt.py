"""
Compaction system prompt + transcript assembly.

Source: src/services/compact/prompt.ts (374 lines).

Without source access this is implemented from the plan's prose:

  > "The compaction system prompt (instruction template)"
  > "build_compact_prompt(messages, options) -> str"
  > "Retention rules: keep last N tool_results, keep critical files, etc."

The prompt is Edwin-domain-aware (slide-app) rather than generic
software-agent because Edwin's compaction will primarily fold older
deck-construction history. A generic source-parity prompt would
under-emphasise the slide-state details that drive the next turn.

Structure of the system prompt:
  1. Role: "you are summarizing a presentation-building conversation"
  2. Output contract: a structured summary with named sections
  3. Retention rules: what MUST be preserved verbatim from history
  4. Format: prose + bullet structure the next-turn LLM can quickly parse

The user-side message wraps the to-summarize transcript with a
``<conversation_history>`` envelope so the model can clearly tell
"the conversation it's summarizing" from "the instructions on how
to summarize."
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence


# ── Constants ──────────────────────────────────────────────────────────────


# Per-block char cap for text and other narrative blocks. Kept
# generous so a long assistant message survives intact.
#
# **Not applied to ``tool_result`` or ``tool_use`` blocks.** Those
# carry the payloads the summary actually depends on — slide HTML,
# fetched documents, memory bodies, the call args that define what
# each tool did. Chopping them mid-payload erases the very details
# the summary is supposed to compress faithfully ("the model created
# 5 slides" is useless without knowing what's on them). The
# transcript-level cap below is the only guard for those.
_BLOCK_CHAR_CAP = 4000

# Maximum chars for the entire transcribed conversation passed to
# the summarizer. Sized to fit the summarizer model's 200K-token
# context window comfortably (≈170K tokens of transcript leaves
# headroom for the system prompt + framing). When the to-summarize
# portion exceeds this we slice down (keeping the head and a tail
# slice) so the summarizer sees both the conversation's starting
# point and what was happening right before the kept tail.
#
# Previously 64K, which forced head-tail middle-truncation on
# typical deck-building conversations with even ~10 slides. Bumped
# so full slide payloads survive into the summary stage by default.
_TRANSCRIPT_CHAR_CAP = 600_000


# ── System prompt ──────────────────────────────────────────────────────────


COMPACTION_SYSTEM_PROMPT = """\
You are summarizing the earlier portion of a presentation-building \
conversation. Your summary will replace those messages in the next \
turn's context, so the next turn's assistant will rely on YOUR \
summary as its only memory of what was discussed and decided before.

Your job: produce a faithful, lossless-where-it-matters summary that \
preserves the information the next turn will need to keep building \
the deck without re-deriving prior decisions.

# Required sections (use these exact headings)

## Project context
- The deck's topic, audience, intended length, and tone if specified.
- Any constraints the user mentioned (template, branding, page count).

## Decisions made
- Concrete choices the user has approved: themes picked, structures \
locked in, sections agreed on. One bullet per decision.

## Slides created so far
- Per-slide list: slide number, title, one-line content summary, and \
the slide's role in the deck (e.g. "title", "section opener", \
"data slide", "CTA closer").
- DO NOT invent slides; only list ones the assistant actually created \
or modified in the conversation history.

## Open questions
- Things the user asked the assistant that haven't been resolved.
- Things the assistant asked the user that haven't been answered.

## User preferences
- Style preferences ("tighter copy", "more visuals"), tone preferences \
("punchier", "more formal"), constraints discovered along the way.

## Recent turn-by-turn highlights
- The last 2-3 substantive exchanges, in chronological order, as \
1-2 sentence summaries each. This gives the next turn enough context \
to follow up naturally without re-asking.

# Rules

- If a section has no content, write "(none)" — DO NOT skip the \
heading. Predictability matters more than concision.
- Quote verbatim only when the exact wording matters (slide titles, \
user-coined terminology, brand names). Otherwise paraphrase tightly.
- Do NOT emit any tool calls, code blocks, or HTML. Output is \
markdown prose only.
- Do NOT include meta-commentary about the summarization itself \
("I am now summarizing..."). Just produce the summary.
- The summary should fit in roughly 600-1500 tokens — tight enough \
to free meaningful context, comprehensive enough that the next \
turn doesn't have to ask the user "remind me what we decided".
"""


# ── Transcript assembly ────────────────────────────────────────────────────


def _block_to_text(block: Any) -> str:
    """Render one content block as transcript text. Lossy by design —
    summarization doesn't need exact JSON; it needs human-readable
    history."""
    if isinstance(block, str):
        return block[:_BLOCK_CHAR_CAP]
    if not isinstance(block, Mapping):
        return str(block)[:_BLOCK_CHAR_CAP]

    btype = block.get("type")
    if btype == "text":
        return str(block.get("text") or "")[:_BLOCK_CHAR_CAP]
    if btype == "tool_use":
        name = block.get("name") or "?"
        # Full call input — CreateSlide's input IS the slide HTML, so
        # chopping it would erase the deck content from the summary's
        # view. Transcript-level cap is the only guard.
        inp = str(block.get("input") or {})
        return f"[Called {name}({inp})]"
    if btype == "tool_result":
        content = block.get("content")
        if isinstance(content, list):
            content_text = "".join(_block_to_text(b) for b in content)
        else:
            content_text = str(content or "")
        # Full content, no per-block cap — see ``_BLOCK_CHAR_CAP`` note.
        return f"[Tool result: {content_text}]"
    if btype == "thinking":
        # Internal model reasoning — not useful for summarization. Skipped
        # entirely so the summarizer focuses on user-visible content.
        return ""
    if btype == "image":
        return "[Image]"
    return ""


def _message_to_transcript_lines(msg: Any) -> list[str]:
    """One message → zero-or-more transcript lines. Empty list if the
    message has no useful content (e.g. all-thinking assistant turn)."""
    if not isinstance(msg, Mapping):
        return []
    inner = msg.get("message")
    if not isinstance(inner, Mapping):
        return []
    role = inner.get("role") or msg.get("type") or "?"
    content = inner.get("content")

    if isinstance(content, str):
        body = content[:_BLOCK_CHAR_CAP].strip()
        return [f"**{role}:** {body}"] if body else []
    if not isinstance(content, list):
        return []

    parts: list[str] = []
    for block in content:
        text = _block_to_text(block).strip()
        if text:
            parts.append(text)
    if not parts:
        return []
    body = "\n".join(parts)
    return [f"**{role}:** {body}"]


def render_transcript(messages: Sequence[Any], *, char_cap: int = _TRANSCRIPT_CHAR_CAP) -> str:
    """Render a list of messages into a transcript string for the
    summarizer's user message.

    If the rendered transcript exceeds ``char_cap`` we keep both ends:
    the earliest history (so the summarizer sees the conversation's
    starting point) and the most-recent-pre-boundary turns (so the
    summarizer can describe how things were trending into the kept
    tail). The middle gets a "(... N messages omitted ...)" marker.
    """
    lines: list[str] = []
    for m in messages:
        lines.extend(_message_to_transcript_lines(m))
    if not lines:
        return "(no messages to summarize)"

    full = "\n\n".join(lines)
    if len(full) <= char_cap:
        return full

    # Truncate from the middle: keep first 40% and last 40% of the budget,
    # with a marker between them. Preserves both ends of the conversation.
    head_budget = int(char_cap * 0.4)
    tail_budget = int(char_cap * 0.4)
    head = full[:head_budget]
    tail = full[-tail_budget:]

    # Snap head/tail to message boundaries so we don't slice inside a turn.
    last_break_in_head = head.rfind("\n\n")
    if last_break_in_head > head_budget // 2:
        head = head[:last_break_in_head]
    first_break_in_tail = tail.find("\n\n")
    if first_break_in_tail > 0 and first_break_in_tail < tail_budget // 2:
        tail = tail[first_break_in_tail + 2 :]

    return f"{head}\n\n... (older middle of conversation omitted for length) ...\n\n{tail}"


def build_compact_user_message(transcript: str, *, manual: bool = False) -> str:
    """Wrap the transcript in tags + a final instruction line.

    ``manual=True`` (from ``/compact``) tweaks the framing slightly so
    the model knows the user explicitly requested the compaction. The
    summary content is the same; only the rationale shifts.
    """
    intent = (
        "The user just ran `/compact` — they want a concise summary right now."
        if manual
        else "The conversation has grown long enough that auto-compaction is being triggered."
    )
    return (
        f"{intent}\n\n"
        f"<conversation_history>\n{transcript}\n</conversation_history>\n\n"
        f"Produce the structured summary now. Use the section headings "
        f"specified in the system prompt. Do not preamble."
    )


__all__ = [
    "COMPACTION_SYSTEM_PROMPT",
    "render_transcript",
    "build_compact_user_message",
]
