"""`clear` — wipe the active conversation's history.

Deletes every message row in the conversation, invalidates the Redis
cache, and zeroes the running token counters. The frontend listens for
the command's ``completed`` lifecycle event and refetches
``/conversations/{id}/messages`` so its local state matches the (now
empty) DB — see useChat.js.

Holds both the Command definition and its ``call`` implementation. The
sibling ``__init__.py`` is a barrel-only re-export per the
``feedback_init_barrel_only`` constraint.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any, cast

from app_logger import get_logger
from app.bridges import db_client

from ...prompts import clear_system_prompt_sections
from ...types.command import Command

log = get_logger(__name__)


async def call(_args: str, ctx: Any) -> dict:
    authorization = getattr(ctx, "authorization", None)
    conversation_id = getattr(ctx, "conversation_id", None)

    if not authorization or not conversation_id:
        return {
            "type": "value",
            "value": (
                "Couldn't clear the conversation: missing request context. "
                "Try reloading the page."
            ),
        }

    try:
        await db_client.clear_messages(authorization, conversation_id)
    except Exception as e:  # noqa: BLE001
        log.warning("clear_messages failed for %s: %s", conversation_id, e)
        return {
            "type": "value",
            "value": f"Couldn't clear the conversation: {e}",
        }

    # Drop memoized dynamic system-prompt sections so a stale env_info /
    # memory / FRC string from before the clear doesn't survive into the
    # next turn. Currently the dynamic tail is empty so this is a no-op,
    # but wiring it now means the dynamic-tail pass doesn't have to
    # re-touch this command.
    clear_system_prompt_sections()

    return {"type": "value", "value": "Conversation cleared."}


async def _load():
    return import_module(__name__)


clear: Command = cast(Command, {
    "type": "local",
    "execution": "server",
    "name": "clear",
    "description": "Clear the conversation history",
    "aliases": ["reset"],
    "supports_non_interactive": True,
    "load": _load,
})
