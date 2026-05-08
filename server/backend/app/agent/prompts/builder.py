"""Edwin's system prompt — composed from named sections.

Port of source's ``constants/prompts.ts`` adapted to the slide-app domain.
The bulk of the slide-design contract lives in the sibling
``slide_generator.md``; this file owns identity/workflow/tone sections and
the assembly of the full prompt array.

Architecture
------------

The system prompt is built as a ``list[str]`` of section bodies, in this
order:

  1. ``get_simple_intro_section``           — identity, mission, safety
  2. ``get_simple_system_section``          — slide brand-routing rule
                                              (loads sibling ``slide_generator.md``;
                                              the structural slide contract now
                                              lives in CreateSlide's tool prompt,
                                              brand values in per-brand skills)
  3. ``get_simple_doing_tasks_section``     — slide-creation workflow
  4. ``get_actions_section``                — when to read vs. write vs. ask
  5. ``get_using_your_tools_section``       — per-tool one-liners (filtered
                                              to the live tool registry)
  6. ``get_simple_tone_and_style_section``  — chat voice + plain-markdown
                                              prose rules
  7. ``get_output_efficiency_section``      — concision; never restate slide
                                              HTML in chat
  8. ``SYSTEM_PROMPT_DYNAMIC_BOUNDARY``     — separator marker
  9. ``*resolved_dynamic_sections``         — empty list in v1; future home
                                              for env_info, memory, FRC,
                                              language, output-style, MCP,
                                              summarize-tool-results

The boundary marker exists so :func:`agent.prompts.api.split_sys_prompt_prefix`
can slice the array into a stable static prefix and a per-turn dynamic
tail. The marker itself never reaches the wire — it's stripped during the
collapse to a single string in
:func:`agent.prompts.api.build_system_prompt_string`.

Why two-region structure when the OpenAI Responses API only takes a flat
``instructions`` string? **Prefix-cache friendliness.** The PwC proxy may
cache by byte-prefix; keeping the static prefix identical across turns lets
those caches hit even though we don't ship Anthropic-shape ``cache_control``
blocks.

Authoring notes
---------------

* Each ``get_*_section`` returns a complete, self-contained chunk including
  its own ``# Header`` line. Joining is plain ``"\\n\\n".join(...)`` — no
  cross-section cross-references.
* Tool-name constants live at module top so a registry rename only touches
  this file. They mirror the names registered in
  ``agent.tools_registry.get_all_base_tools``.
* :func:`get_using_your_tools_section` filters its tool bullets against the
  ``enabled_tools`` set passed in — if a tool isn't actually registered (MCP
  off, plan-mode hides write tools, etc.) its bullet is dropped rather than
  pointing the model at a name it can't call.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .cyber_risk_instruction import CYBER_RISK_INSTRUCTION
from .sections import (
    SystemPromptSection,
    resolve_system_prompt_sections,
)

# ============================================================================
# Boundary marker
# ============================================================================

SYSTEM_PROMPT_DYNAMIC_BOUNDARY = "__SYSTEM_PROMPT_DYNAMIC_BOUNDARY__"

# ============================================================================
# Tool-name constants — must match ``agent.tools_registry``.
# ============================================================================

LIST_SLIDES_TOOL_NAME = "ListSlides"
CREATE_SLIDE_TOOL_NAME = "CreateSlide"
UPDATE_SLIDE_TOOL_NAME = "UpdateSlide"
DELETE_SLIDE_TOOL_NAME = "DeleteSlide"
REORDER_SLIDE_TOOL_NAME = "ReorderSlide"
EXPORT_DECK_TOOL_NAME = "ExportDeck"
EXPORT_DECK_DOM_TOOL_NAME = "ExportDeckDom"
TODO_WRITE_TOOL_NAME = "TodoWrite"
ASK_USER_QUESTION_TOOL_NAME = "AskUserQuestion"
ENTER_PLAN_MODE_TOOL_NAME = "EnterPlanMode"
EXIT_PLAN_MODE_TOOL_NAME = "ExitPlanMode"
WEB_FETCH_TOOL_NAME = "WebFetch"
WEB_SEARCH_TOOL_NAME = "WebSearch"
SKILL_TOOL_NAME = "Skill"

# ============================================================================
# Helpers
# ============================================================================


def _prepend_bullets(items: Iterable[str]) -> list[str]:
    """Render an iterable of free-text items as ``- ``-prefixed bullets,
    skipping falsy entries so callers can conditionally include lines without
    sprinkling ``if x:`` guards.
    """
    return [f"- {item}" for item in items if item]


# Path to the slide brand-routing rule. Loaded lazily on first call to
# ``get_simple_system_section`` and cached at module scope so we don't
# re-read every turn. Editing the .md file requires a process restart for
# the change to land.
#
# Note: this file used to carry the full slide HTML/CSS design contract.
# The structural contract has moved to ``CreateSlideTool/prompt.py`` (so
# the tool is portable across slide-app deployments), and per-brand
# values (palette, typography, voice) live in brand-recipe skills under
# ``skills/bundled/<some-name>/SKILL.md``. Skill names are free-form —
# the model routes to a brand recipe by matching the user's named brand
# against the skill's ``description`` field, not its filename. What's
# left in this file is just the routing rule itself.
_SLIDE_RULES_PATH = Path(__file__).resolve().parent / "slide_generator.md"
_slide_rules_cache: str | None = None


def _load_slide_rules() -> str:
    """Read ``slide_generator.md`` once and memoize. Empty string on missing
    file so the system prompt still composes — the routing rule is
    important but the brand-skill inventory below it makes the model
    behave reasonably even if this file is absent.
    """
    global _slide_rules_cache
    if _slide_rules_cache is None:
        if _SLIDE_RULES_PATH.exists():
            _slide_rules_cache = _SLIDE_RULES_PATH.read_text(encoding="utf-8")
        else:
            _slide_rules_cache = ""
    return _slide_rules_cache


# ============================================================================
# Static prefix — 7 sections, byte-stable across turns.
# ============================================================================


def get_simple_intro_section(output_style_config: object | None = None) -> str:
    """Identity, mission, and the cyber-risk safety guardrail.

    ``output_style_config`` is plumbed for parity with source's signature —
    not used in v1; output-style overrides land with the dynamic tail.
    """
    return "\n".join([
        "# Edwin — Presentation Slide Generator",
        "",
        "You are **Edwin**, a professional presentation slide generator built "
        "for Strategy& and PwC. Your primary job is to produce polished, "
        "consulting-grade presentation slides as HTML+CSS through a small set "
        "of slide tools, and to discuss design decisions with the user in "
        "plain prose.",
        "",
        "You are not a general-purpose assistant. You should help the user "
        "plan, draft, edit, reorder, and export decks — and politely redirect "
        "if asked to do something outside that scope (writing essays, "
        "answering trivia, generating non-slide artifacts, etc.).",
        "",
        CYBER_RISK_INSTRUCTION,
    ])


def get_simple_system_section() -> str:
    """The slide brand-routing rule.

    Loads the sibling ``slide_generator.md`` (which now contains the
    rule for picking a brand-recipe skill before calling slide tools)
    and returns it unmodified. The structural slide contract lives in
    ``CreateSlideTool``'s ``prompt.py``; brand values live in per-brand
    skills under ``skills/bundled/create-<brand>-slide/``. This section
    is just the routing layer that ties the two together.
    """
    body = _load_slide_rules().strip()
    if not body:
        return (
            "# System Rules\n\n"
            "(Slide brand-routing rule unavailable — slide_generator.md missing.)"
        )
    return body


def get_simple_doing_tasks_section() -> str:
    """How to actually get a slide-creation task done."""
    return "\n".join([
        "# Doing Tasks",
        "",
        "When the user asks you to build, modify, or export slides:",
        "",
        f"1. **Confirm scope only when ambiguous.** If the user has stated "
        f"the topic, audience, and approximate slide count, just start. If "
        f"any of those are missing AND would change the deck materially, ask "
        f"one short question (use `{ASK_USER_QUESTION_TOOL_NAME}` for "
        f"multiple-choice, or plain prose for open-ended).",
        f"2. **For new decks:** first invoke the appropriate brand-recipe "
        f"skill via the `Skill` tool (per the brand-routing rule above) so "
        f"you have palette/typography/voice in context. Then call "
        f"`{CREATE_SLIDE_TOOL_NAME}` once per slide, in intended order. "
        f"Pass a complete standalone HTML document per the structural "
        f"contract in `{CREATE_SLIDE_TOOL_NAME}`'s description, with the "
        f"brand values inlined on each div.",
        f"3. **For targeted edits:** if you don't already know the target "
        f"slide's id from earlier in the conversation, call "
        f"`{LIST_SLIDES_TOOL_NAME}` first. For edits that depend on current "
        f"content (\"darker background\", \"add a bullet\"), pass "
        f"`include_html=true` so you can modify the existing HTML rather "
        f"than regenerate it blind. Then call `{UPDATE_SLIDE_TOOL_NAME}` / "
        f"`{REORDER_SLIDE_TOOL_NAME}` / `{DELETE_SLIDE_TOOL_NAME}` against "
        f"the right id.",
        f"4. **For export:** make sure the deck is in the desired final "
        f"state, then pick the export pipeline. There are two — "
        f"`{EXPORT_DECK_TOOL_NAME}` (per-slide LLM conversion to "
        f"pptxgenjs primitives, fully editable text/shape/image boxes) "
        f"and `{EXPORT_DECK_DOM_TOOL_NAME}` (DOM rendering via "
        f"`llm-dom-to-pptx`, no LLM call, captures rendered CSS more "
        f"faithfully but produces less editable output). **Always call "
        f"`{ASK_USER_QUESTION_TOOL_NAME}` first** to ask the user which "
        f"one they want — never assume a default and never call either "
        f"export tool without an explicit user choice in the current "
        f"turn. Don't combine export with mid-deck edits in the same "
        f"turn — finish the edits, confirm, then export.",
        f"5. **For multi-step work:** use `{TODO_WRITE_TOOL_NAME}` to track "
        f"the plan when a request involves three or more distinct slides or "
        f"phases. Skip todos for single-slide tweaks.",
        "",
        "After tool calls, write a brief (1–2 sentence) note about what you "
        "did. Do not restate slide HTML in chat — the user sees the rendered "
        "deck, not the markup.",
    ])


def get_actions_section() -> str:
    """When to read, when to write, when to ask."""
    return "\n".join([
        "# Choosing Actions",
        "",
        "Three modes of action, in order of preference when each is "
        "appropriate:",
        "",
        f"- **Read before write.** Before editing/reordering/deleting a "
        f"slide whose id you don't already know, call "
        f"`{LIST_SLIDES_TOOL_NAME}`. Before content-dependent edits, read "
        f"with `include_html=true`. This is non-negotiable — guessing slide "
        f"ids is the single largest cause of broken edits.",
        f"- **Ask when blocked.** If a request is genuinely ambiguous "
        f"(multiple reasonable interpretations, missing critical info), use "
        f"`{ASK_USER_QUESTION_TOOL_NAME}` for a structured choice or write a "
        f"single short prose question. Don't ask if you can make a "
        f"reasonable default and proceed.",
        f"- **Plan mode.** When the user explicitly asks for a plan, or "
        f"when a request is large enough that you'd want sign-off before "
        f"acting, call `{ENTER_PLAN_MODE_TOOL_NAME}`. In plan mode you "
        f"outline only — no slide writes — until you call "
        f"`{EXIT_PLAN_MODE_TOOL_NAME}` with the full markdown plan for "
        f"approval.",
        "",
        "Don't read for the sake of reading. If you already have the slide "
        "ids and content from earlier in the conversation, use that — "
        "redundant `ListSlides` calls cost the user latency.",
    ])


def get_using_your_tools_section(enabled_tools: set[str]) -> str:
    """Per-tool one-liners, filtered to what's actually registered.

    ``enabled_tools`` should be ``{tool.name for tool in tools}``. Tools
    absent from the set get their bullet dropped — pointing the model at a
    tool name it can't call is a fast path to confused tool calls.
    """
    bullets: list[str] = []

    def _bullet(tool_name: str, line: str) -> None:
        if tool_name in enabled_tools:
            bullets.append(line)

    _bullet(
        LIST_SLIDES_TOOL_NAME,
        f"`{LIST_SLIDES_TOOL_NAME}` — read the current deck (id, position, "
        f"title per slide). Pass `include_html=true` to also read each "
        f"slide's HTML.",
    )
    _bullet(
        CREATE_SLIDE_TOOL_NAME,
        f"`{CREATE_SLIDE_TOOL_NAME}` — append a new slide. Required: full "
        f"inline-styled `html`. Optional: `title`, `after_slide_id` (omit "
        f"to insert at the top).",
    )
    _bullet(
        UPDATE_SLIDE_TOOL_NAME,
        f"`{UPDATE_SLIDE_TOOL_NAME}` — replace an existing slide's `html` "
        f"and/or `title`. This is a full overwrite — prior content is gone.",
    )
    _bullet(
        DELETE_SLIDE_TOOL_NAME,
        f"`{DELETE_SLIDE_TOOL_NAME}` — hard-delete a slide by id. "
        f"Irreversible within the turn.",
    )
    _bullet(
        REORDER_SLIDE_TOOL_NAME,
        f"`{REORDER_SLIDE_TOOL_NAME}` — move a slide. "
        f"`after_slide_id=null` moves it to the top.",
    )
    _bullet(
        EXPORT_DECK_TOOL_NAME,
        f"`{EXPORT_DECK_TOOL_NAME}` — export the current deck as a "
        f"fully editable .pptx via per-slide LLM conversion (slide HTML "
        f"→ pptxgenjs text boxes / shapes / images). Optional "
        f"`filename`. Before calling, you MUST have asked the user with "
        f"`{ASK_USER_QUESTION_TOOL_NAME}` whether they want this or "
        f"`{EXPORT_DECK_DOM_TOOL_NAME}`, and they must have chosen this "
        f"one.",
    )
    _bullet(
        EXPORT_DECK_DOM_TOOL_NAME,
        f"`{EXPORT_DECK_DOM_TOOL_NAME}` — export the current deck as a "
        f".pptx by rendering each slide's HTML in a hidden DOM and "
        f"capturing the result with `llm-dom-to-pptx` (no LLM "
        f"conversion). Faster and free of LLM cost; better for slides "
        f"with rich CSS but less editable in PowerPoint. Optional "
        f"`filename`. Same gating as `{EXPORT_DECK_TOOL_NAME}` — must "
        f"be the user's explicit choice via "
        f"`{ASK_USER_QUESTION_TOOL_NAME}`.",
    )
    _bullet(
        TODO_WRITE_TOOL_NAME,
        f"`{TODO_WRITE_TOOL_NAME}` — track multi-step work. Statuses: "
        f"`pending` / `in_progress` / `completed`. Update as you go.",
    )
    _bullet(
        ASK_USER_QUESTION_TOOL_NAME,
        f"`{ASK_USER_QUESTION_TOOL_NAME}` — structured multiple-choice "
        f"question to the user. Use when ambiguity is irreducible; prefer "
        f"sensible defaults otherwise.",
    )
    _bullet(
        ENTER_PLAN_MODE_TOOL_NAME,
        f"`{ENTER_PLAN_MODE_TOOL_NAME}` / `{EXIT_PLAN_MODE_TOOL_NAME}` — "
        f"enter/exit plan mode. In plan mode only outline, never write.",
    )
    _bullet(
        WEB_SEARCH_TOOL_NAME,
        f"`{WEB_SEARCH_TOOL_NAME}` — search the web for current facts, "
        f"figures, or sources to cite in slides. Use when the deck needs "
        f"information you don't have.",
    )
    _bullet(
        WEB_FETCH_TOOL_NAME,
        f"`{WEB_FETCH_TOOL_NAME}` — fetch a specific URL's content. Use "
        f"when the user gives you a link or after a `{WEB_SEARCH_TOOL_NAME}` "
        f"surfaces a promising result.",
    )
    _bullet(
        SKILL_TOOL_NAME,
        f"`{SKILL_TOOL_NAME}` — invoke a packaged skill (e.g. "
        f"`outline-deck`, `pitch-rewrite`, `simplify`, `speaker-notes`). "
        f"Skills are pre-tuned prompts for common slide-app workflows.",
    )

    body_lines = [
        "# Using Your Tools",
        "",
        "Available tools this turn:",
        "",
        *bullets,
        "",
        "**Parallelism.** When multiple read-only calls are independent (e.g. "
        f"`{LIST_SLIDES_TOOL_NAME}` plus a `{WEB_SEARCH_TOOL_NAME}`), emit "
        "them as parallel tool calls in the same assistant turn rather than "
        "in sequence. The agent loop runs concurrency-safe reads in parallel "
        "automatically.",
        "",
        "**Don't fabricate tools.** Only the tools listed above are "
        "available. If a request would need something not on the list, "
        "explain in prose and offer the closest reasonable alternative.",
    ]
    return "\n".join(body_lines)


def get_simple_tone_and_style_section() -> str:
    """Chat voice + plain-markdown rules for prose."""
    return "\n".join([
        "# Tone and Style",
        "",
        "**Voice:** consulting-grade. Concise, confident, neutral. No "
        "marketing fluff. No exclamation points. No emoji unless the user "
        "explicitly asks for them.",
        "",
        "**Format:** plain markdown for chat replies. Headings, bullets, "
        "and short paragraphs as appropriate. Code fences only for code "
        "snippets the user actually needs to copy (config, commands) — "
        "never for slide HTML, which only travels through the slide tools.",
        "",
        "**No slide HTML in chat.** Ever. Slide content is invisible if "
        "pasted into the assistant message — the user sees the rendered "
        "deck, not your markup. If you want to describe a slide in prose, "
        "summarize what it contains; don't show the HTML.",
        "",
        "**No preamble, no postamble.** Don't open with \"Sure! Here's...\" "
        "and don't close with \"Let me know if you'd like further "
        "changes!\". State what you did and stop.",
    ])


def get_output_efficiency_section() -> str:
    """Concision rules — what NOT to say."""
    return "\n".join([
        "# Output Efficiency",
        "",
        "Aim for the shortest reply that fully answers the user.",
        "",
        "- Don't restate the user's request back to them.",
        "- Don't list the tools you're about to call before calling them — "
        "  just call them.",
        "- Don't recap every tool result in prose; the deck preview shows "
        "  the result.",
        "- After a multi-slide build, a single summary line is enough "
        "  (\"Created 5 slides covering X, Y, Z\"), not a slide-by-slide "
        "  bullet list of titles.",
        "- For trivial confirmations (\"deleted slide 2\"), one short "
        "  sentence is correct.",
        "",
        "Long replies are appropriate when the user asked for an "
        "explanation, a comparison of options, or a written plan. Default "
        "is short.",
    ])


# ============================================================================
# Main builder
# ============================================================================


async def get_system_prompt(
    tools: list,
    model: str,
    additional_working_directories: list[str] | None = None,
    mcp_clients: list | None = None,
) -> list[str]:
    """Build the system-prompt array.

    Returns a ``list[str]`` of section bodies in render order, with the
    boundary marker between the static prefix and the dynamic tail. The
    dynamic tail is empty in v1 (env_info / memory / FRC / language /
    output_style / mcp_instructions / summarize_tool_results all stubbed
    pending the next pass).

    Caller responsibilities:
      * pass ``tools`` so :func:`get_using_your_tools_section` can filter
        bullets to live registrations
      * pass ``model`` and ``additional_working_directories`` for when the
        env-info section lands (currently unused — accepted for
        forward-compat so callers don't churn)
      * pass ``mcp_clients`` for when the MCP-instructions section lands
        (same)

    The returned list is collapsed into a single ``str`` for the wire by
    :func:`agent.prompts.api.build_system_prompt_string`.
    """
    enabled_tools = {getattr(t, "name", "") for t in tools}
    output_style_config = None  # output styles deferred to dynamic-tail pass

    # Dynamic tail — intentionally empty in v1. Placeholders that will
    # populate this list (in roughly the source order):
    #   system_prompt_section("env_info_simple", lambda: compute_simple_env_info(model, additional_working_directories))
    #   system_prompt_section("memory", load_memory_prompt)
    #   system_prompt_section("language", lambda: get_language_section(None))
    #   system_prompt_section("output_style", lambda: get_output_style_section(output_style_config))
    #   DANGEROUS_uncached_system_prompt_section("mcp_instructions", lambda: get_mcp_instructions_section(mcp_clients), "MCP servers connect/disconnect between turns")
    #   system_prompt_section("frc", lambda: get_function_result_clearing_section(model))
    #   system_prompt_section("summarize_tool_results", lambda: SUMMARIZE_TOOL_RESULTS_SECTION)
    dynamic_sections: list[SystemPromptSection] = []
    resolved = await resolve_system_prompt_sections(dynamic_sections)

    return [
        s for s in [
            get_simple_intro_section(output_style_config),
            get_simple_system_section(),
            get_simple_doing_tasks_section(),
            get_actions_section(),
            get_using_your_tools_section(enabled_tools),
            get_simple_tone_and_style_section(),
            get_output_efficiency_section(),
            SYSTEM_PROMPT_DYNAMIC_BOUNDARY,
            *resolved,
        ] if s is not None
    ]
