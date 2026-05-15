"""Message helpers — minimal port of src/utils/messages.ts.

v1 ships only what AgentTool / runAgent need. Other helpers (assistant
messages, content-block utilities) land alongside features that need them.
"""

from __future__ import annotations

from typing import Any


def create_user_message(content: Any) -> dict[str, Any]:
    """Construct a user-shape message for the loop's message dict format.

    Mirrors source ``createUserMessage`` (src/utils/messages.ts). Accepts:
      - a plain string → wrapped as a single text block (the loop's wire
        format permits string OR list-of-blocks for ``message.content``)
      - a list of content blocks → passed through verbatim
      - a single content-block dict → wrapped in a list

    The returned shape matches what query_loop expects in
    ``state.messages``: ``{type: "user", message: {role, content}}``.
    """
    if isinstance(content, str):
        msg_content: Any = content
    elif isinstance(content, dict):
        msg_content = [content]
    else:
        msg_content = list(content) if content is not None else []
    return {
        "type": "user",
        "message": {"role": "user", "content": msg_content},
    }
