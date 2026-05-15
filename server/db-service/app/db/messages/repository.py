"""Message repository — transactional append + history reads."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from app.db import Pool
from app.db.messages import queries
from app.db.messages.models import Message


async def append_message(
    pool: Pool,
    *,
    conversation_id: UUID,
    role: str,
    content: list[dict[str, Any]],
) -> Message:
    """Insert a message and bump conversation bookkeeping in one transaction.

    Concurrent inserts on the same conversation are guarded by the UNIQUE
    (conversation_id, sequence) constraint — on a collision, the transaction
    rolls back and the caller retries (db-service router surfaces a 409).
    """
    content_json = json.dumps(content)
    async with pool.acquire() as conn:
        async with conn.transaction():
            sequence = await conn.fetchval(queries.NEXT_SEQUENCE, conversation_id)
            row = await conn.fetchrow(queries.INSERT, conversation_id, sequence, role, content_json)
            await conn.execute(queries.BUMP_CONVERSATION, conversation_id)
    return Message.from_record(row)


async def list_messages(
    pool: Pool,
    conversation_id: UUID,
    *,
    before_sequence: int | None = None,
    limit: int = 50,
) -> list[Message]:
    """Return messages for a conversation.

    Default: full history in ascending sequence order.
    With ``before_sequence``: the ``limit`` most recent messages strictly
    older than that sequence, returned in ascending order (frontend prepends
    them to the existing buffer).
    """
    if before_sequence is None:
        rows = await pool.fetch(queries.LIST_BY_CONVERSATION, conversation_id)
        return [Message.from_record(r) for r in rows]

    rows = await pool.fetch(queries.LIST_BEFORE_SEQUENCE, conversation_id, before_sequence, limit)
    # DESC in SQL for LIMIT, reverse here so callers see ascending order.
    return [Message.from_record(r) for r in reversed(rows)]


async def delete_all_messages(pool: Pool, conversation_id: UUID) -> int:
    """Truncate every message in a conversation.

    Returns the number of rows deleted (informational only — the caller
    won't act on the count). Conversation bookkeeping (``message_count``,
    token counters) is reset by the conversations repo in the same caller
    transaction; we keep this function single-purpose.
    """
    result = await pool.execute(queries.DELETE_ALL_FOR_CONVERSATION, conversation_id)
    # asyncpg returns "DELETE N" — pull the count for logging.
    try:
        return int(result.rsplit(" ", 1)[-1])
    except (ValueError, IndexError):
        return 0
