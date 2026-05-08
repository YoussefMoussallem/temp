"""
Helpers for synthesizing the user-shape messages a slash-command emits.

Source: src/utils/createCommandInputMessage.ts (just the
``createCommandInputMessage`` half) — together with the small
``user_message`` / ``wrap_xml`` helpers that both the slash-command
dispatcher and the parent ``process_user_input`` need.

Kept in one file so a single import in either dispatcher pulls everything,
and the LOCAL_COMMAND_STDOUT_TAG wrapping convention has exactly one home.
"""

from __future__ import annotations

from ..constants.xml import LOCAL_COMMAND_STDOUT_TAG


def user_message(text_or_content: str | list[dict]) -> dict:
    """Wrap a string or a list of content blocks into a loop-shape ``user``
    message dict — i.e. ``{"type":"user","message":{"role":"user","content":[...]}}``.
    """
    if isinstance(text_or_content, str):
        content: list[dict] = [{"type": "text", "text": text_or_content}]
    else:
        content = list(text_or_content)
    return {"type": "user", "message": {"role": "user", "content": content}}


def wrap_xml(tag: str, body: str) -> str:
    """Return ``<tag>body</tag>``. Used by the slash-command dispatcher to
    wrap command-name / args / message / stdout payloads."""
    return f"<{tag}>{body}</{tag}>"


def create_command_input_message(stdout: str) -> dict:
    """Synthetic user message holding a local-command's stdout, wrapped in
    ``LOCAL_COMMAND_STDOUT_TAG`` so renderers can format it as terminal-like
    output. Source name: ``createCommandInputMessage``."""
    return user_message(wrap_xml(LOCAL_COMMAND_STDOUT_TAG, stdout))
