"""
Parent dispatcher for one turn's user input.

Source: src/utils/processUserInput/processUserInput.tsx (the inline
top-level branch). Two cases:
  - input starts with ``/`` → delegate to ``process_slash_command``
  - otherwise → return the input verbatim as a single ``user`` message,
    with any attachments interleaved as content blocks. This is the
    "passthrough" case where the model handles things normally.

Callers (e.g. the ``/turn`` route handler) talk to this single entry
point and never need to know about the slash dispatcher directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..create_command_input_message import user_message
from ..slash_command_parsing import is_slash_command
from .process_slash_command import ProcessedInput, process_slash_command

if TYPE_CHECKING:
    from ...Tool import ToolUseContext


async def process_user_input(
    input_str: str,
    ctx: "ToolUseContext",
    attachments: list[dict] | None = None,
) -> ProcessedInput:
    """Resolve one user_input into the messages that should be persisted +
    sent to the model this turn.

    ``attachments`` is a list of content blocks (typically image blocks)
    that ride along with the input. For the slash branch they get appended
    after the expanded command messages; for the passthrough branch they
    get interleaved into the user message itself.
    """
    attachments = list(attachments or [])

    if is_slash_command(input_str):
        return await process_slash_command(input_str, ctx, attachments)

    # Passthrough: a plain user message. Mix attachments in as additional
    # content blocks so the model sees them on the same turn.
    content_blocks: list[dict] = [{"type": "text", "text": input_str}]
    content_blocks.extend(attachments)
    return ProcessedInput(
        messages=[user_message(content_blocks)],
        should_query=True,
    )
