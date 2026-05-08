"""`plan` — prompt-type. Tells the model to switch into plan mode by calling
the ``EnterPlanMode`` tool, outlining the approach with ``TodoWrite``, then
exiting via ``ExitPlanMode`` for user approval.

Holds both the Command definition and its ``get_prompt_for_command``
implementation. The sibling ``__init__.py`` is a barrel-only re-export
per the ``feedback_init_barrel_only`` constraint.
"""

from __future__ import annotations

from typing import Any, cast

from ...types.command import Command


async def _get_prompt(args: str, _ctx: Any) -> list[dict]:
    text = (
        "Enter plan mode by calling EnterPlanMode. Outline your approach: "
        "list every step with TodoWrite, explain your decisions, then call "
        "ExitPlanMode with your complete plan for my approval."
    )
    task = (args or "").strip()
    if task:
        text += f"\n\nTask: {task}"
    return [{"type": "text", "text": text}]


plan: Command = cast(Command, {
    "type": "prompt",
    "execution": "server",
    "name": "plan",
    "description": "Enter plan mode for the next request",
    "argument_hint": "[task]",
    "source": "builtin",
    "progress_message": "entering plan mode",
    "content_length": 200,
    "get_prompt_for_command": _get_prompt,
})
