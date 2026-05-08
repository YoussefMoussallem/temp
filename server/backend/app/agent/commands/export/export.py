"""`export` — prompt-type. Expand into a model instruction that emits the
current deck as a portable file (HTML by default, optionally PDF/etc).

Holds both the Command definition and its ``get_prompt_for_command``
implementation. The sibling ``__init__.py`` is a barrel-only re-export
per the ``feedback_init_barrel_only`` constraint.
"""

from __future__ import annotations

from typing import Any, cast

from ...types.command import Command


async def _get_prompt(args: str, _ctx: Any) -> list[dict]:
    fmt = (args or "html").strip()
    text = (
        f"Export the current slide deck to {fmt}. "
        "Use the existing slide tools to read every slide in order, then "
        "package them into one deliverable. Report the output path when done."
    )
    return [{"type": "text", "text": text}]


export: Command = cast(Command, {
    "type": "prompt",
    "execution": "server",
    "name": "export",
    "description": "Export the current deck (default: HTML)",
    "argument_hint": "[format]",
    "source": "builtin",
    "progress_message": "exporting deck",
    "content_length": 200,
    "get_prompt_for_command": _get_prompt,
})
