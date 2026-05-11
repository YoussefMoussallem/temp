"""Structure natural-language memory input into the persisted schema.

Phase 3.5 UX: end users write memories in plain English ("remember that
I don't want emoji in slides"). The DB row needs the structured shape —
slug / type / name / description / body — so the agent's read tools
can index and address it. This module bridges the two with a single
LLM call.

The LLM is also given the existing memory index so it can detect
contradicting / superseding entries and reuse their slug. That keeps
the "never create a sibling that contradicts an existing entry" rule
in force when the entry point is the UI rather than the agent tools.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app_logger import get_logger
from app.bridges import app_settings_client
from app.bridges.provider_bridge import get_adapter

log = get_logger(__name__)


_USER_TYPES = ("user", "feedback", "reference")
_PROJECT_TYPES = ("project", "decision", "stakeholder", "reference")

# Same fence-stripping as ExportDeck — models occasionally wrap their
# JSON in ```json … ``` despite the prompt asking otherwise; cleanly
# strip both opening and closing fences in one regex.
_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


_USER_TYPE_GUIDE = (
    "  - `user`: about the user's identity, role, or stable preferences\n"
    "  - `feedback`: a correction or validated approach to carry across "
    "every conversation\n"
    "  - `reference`: a pointer to an external resource that applies "
    "broadly"
)

_PROJECT_TYPE_GUIDE = (
    "  - `project`: a general fact about this deck (scope, key message)\n"
    "  - `decision`: an explicit choice made for this deck\n"
    "  - `stakeholder`: about an audience member, reviewer, or sponsor\n"
    "  - `reference`: a pointer to an external resource specific to this "
    "deck"
)


def _build_system_prompt(scope: str, existing_index: list[dict[str, Any]]) -> str:
    """Compose the structuring-LLM system prompt.

    The existing index is rendered as bullet lines (slug, type, name,
    description) so the model can spot supersession candidates and
    reuse a slug rather than creating a contradicting sibling — the
    same workflow rule the agent tools enforce.
    """
    type_guide = _USER_TYPE_GUIDE if scope == "user" else _PROJECT_TYPE_GUIDE
    valid_types = _USER_TYPES if scope == "user" else _PROJECT_TYPES

    if existing_index:
        existing_lines = "\n".join(
            f"  - [{m['slug']}] ({m['type']}) {m['name']} — {m['description']}"
            for m in existing_index
        )
        existing_block = (
            "\nExisting memories in this scope (reuse a slug if the new "
            "note supersedes / refines / contradicts one of these — do "
            "NOT create a sibling that contradicts an existing entry):\n"
            f"{existing_lines}\n"
        )
    else:
        existing_block = "\n(No existing memories yet in this scope.)\n"

    return (
        f"You convert a user's natural-language note into a structured "
        f"long-term memory entry for Edwin (a slide-generation tool).\n\n"
        f"Scope: {scope}\n"
        f"{existing_block}\n"
        f"Output a single JSON object with these fields:\n\n"
        f"  - `slug`: snake_case identifier, ≤64 chars, descriptive of "
        f"the topic. If the new note clearly supersedes / refines an "
        f"existing entry, REUSE that entry's slug. Otherwise pick a "
        f"fresh descriptive slug.\n"
        f"  - `type`: one of {list(valid_types)}. Pick the best fit:\n"
        f"{type_guide}\n"
        f"  - `name`: short human-readable title, ≤120 chars. Sentence "
        f"case. No quotes.\n"
        f"  - `description`: one-line hook for the memory index, ≤150 "
        f"chars. Concrete and specific (a future read should know "
        f"whether to expand this from the description alone).\n"
        f"  - `body`: full content as markdown. Preserve the user's "
        f"intent. For preferences / decisions, structure with a one-"
        f"line rule, then **Why:** and **How to apply:** lines if "
        f"appropriate.\n\n"
        f"Output ONLY the JSON object. No preamble, no commentary, "
        f"no code fences."
    )


def _strip_fences(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    return _FENCE_RE.sub("", stripped).strip()


async def structure_memory_text(
    *,
    authorization: str,
    text: str,
    scope: str,
    existing_index: list[dict[str, Any]],
    force_slug: str | None = None,
) -> dict[str, str]:
    """Call the default LLM to turn ``text`` into structured memory fields.

    Returns a dict ready to pass into ``db_client.upsert_user_memory`` or
    ``db_client.upsert_project_memory`` (whichever scope was requested).
    Raises ``ValueError`` if the model returns malformed JSON or omits a
    required field — caller surfaces this to the user as a 4xx.

    ``force_slug`` is set when the caller is editing a specific existing
    entry (the slug is the addressable handle — preserving it means the
    upsert overwrites in place rather than potentially creating a
    sibling if the LLM picks a slightly different slug for the
    refined text).
    """
    from llm_provider import ChatRequest, Message  # noqa: PLC0415

    if not text or not text.strip():
        raise ValueError("text is empty")
    if scope not in ("user", "project"):
        raise ValueError(f"invalid scope: {scope!r}")

    valid_types = _USER_TYPES if scope == "user" else _PROJECT_TYPES

    models = await app_settings_client.resolve(authorization)
    model = models.default_model

    adapter = get_adapter()
    request = ChatRequest(
        model=model,
        messages=[Message(role="user", content=text.strip())],
        thinking=False,
    )
    raw = await adapter.generate(
        request, _build_system_prompt(scope, existing_index),
    )

    cleaned = _strip_fences(raw)
    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError as e:
        log.warning(
            "memory structuring: LLM returned non-JSON; raw=%r", raw[:300],
        )
        raise ValueError(f"LLM returned non-JSON: {e}") from e

    if not isinstance(result, dict):
        raise ValueError(f"LLM output must be a JSON object, got {type(result).__name__}")

    required = ("slug", "type", "name", "description", "body")
    missing = [f for f in required if not result.get(f)]
    if missing:
        raise ValueError(f"LLM output missing required fields: {missing}")

    # Coerce + trim. The db-service does its own validation but we want
    # clean errors before the round-trip — and the LLM occasionally
    # produces edge-case strings (extra whitespace, fence remnants).
    if force_slug:
        # Edit mode: ignore whatever slug the LLM picked. Keeping the
        # original slug is what makes "edit" an overwrite rather than
        # a fork.
        slug = force_slug
    else:
        slug = re.sub(r"[^a-z0-9_]", "_", str(result["slug"]).strip().lower())
        slug = re.sub(r"_+", "_", slug).strip("_")[:64]
        if not slug:
            raise ValueError("LLM produced an empty slug after normalization")

    type_ = str(result["type"]).strip().lower()
    if type_ not in valid_types:
        # Defensive fallback — the model occasionally invents tags. Map
        # to the most permissive one in scope rather than rejecting.
        log.warning(
            "memory structuring: LLM produced invalid type=%r for scope=%s; "
            "coercing to %r", type_, scope, valid_types[0],
        )
        type_ = valid_types[0]

    return {
        "slug": slug,
        "type": type_,
        "name": str(result["name"]).strip()[:120],
        "description": str(result["description"]).strip()[:150],
        "body": str(result["body"]).strip(),
    }
