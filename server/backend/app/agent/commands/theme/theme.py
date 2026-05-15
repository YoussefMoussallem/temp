"""`theme` — prompt-type. Expand into an instruction to re-style the deck.

Holds both the Command definition and its ``get_prompt_for_command``
implementation. The sibling ``__init__.py`` is a barrel-only re-export
per the ``feedback_init_barrel_only`` constraint.
"""

from __future__ import annotations

from typing import Any, cast

from ...types.command import Command


async def _get_prompt(args: str, _ctx: Any) -> list[dict]:
    theme_name = (args or "default").strip()
    text = (
        f"Apply the `{theme_name}` theme across every slide in the current "
        "deck. Keep the content identical — only the visual styling changes. "
        "Update slides one at a time so you can verify each looks right "
        "before moving on."
    )
    return [{"type": "text", "text": text}]


theme: Command = cast(
    Command,
    {
        "type": "prompt",
        "execution": "server",
        "name": "theme",
        "description": "Apply a theme to the current deck",
        "argument_hint": "[theme-name]",
        "source": "builtin",
        "progress_message": "applying theme",
        "content_length": 200,
        "get_prompt_for_command": _get_prompt,
    },
)
