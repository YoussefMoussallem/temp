"""`new-deck` — prompt-type. Wipe deck context and start a fresh one.

The user-visible name is ``new-deck`` (hyphenated, source-faithful). The
Python package directory is ``new_deck`` because hyphens aren't valid in
identifiers — only the ``name`` field of the ``Command`` object is what
the parser matches against.

Holds both the Command definition and its ``get_prompt_for_command``
implementation. The sibling ``__init__.py`` is a barrel-only re-export
per the ``feedback_init_barrel_only`` constraint.
"""

from __future__ import annotations

from typing import Any, cast

from ...types.command import Command


async def _get_prompt(args: str, _ctx: Any) -> list[dict]:
    topic = (args or "").strip()
    if topic:
        text = (
            f"Start a brand-new slide deck on the topic: {topic}. "
            "Discard any prior deck context — treat the existing slide list "
            "as historical and don't reuse it. Begin by proposing a deck "
            "outline (titles + 1-line summary per slide), then wait for the "
            "user to confirm or revise before generating any slide content."
        )
    else:
        text = (
            "Start a brand-new slide deck. Discard any prior deck context — "
            "treat the existing slide list as historical and don't reuse it. "
            "Ask the user for the topic, intended audience, and key takeaways "
            "before proposing an outline. Don't generate any slide content "
            "until those three are confirmed."
        )
    return [{"type": "text", "text": text}]


new_deck: Command = cast(Command, {
    "type": "prompt",
    "execution": "server",
    "name": "new-deck",
    "description": "Start a fresh slide deck",
    "argument_hint": "[topic]",
    "source": "builtin",
    "progress_message": "starting a new deck",
    "content_length": 300,
    "get_prompt_for_command": _get_prompt,
})
