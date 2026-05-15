"""Conversation repository — all conversations DB operations."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from app.db import Pool
from app.db.conversations import queries
from app.db.conversations.models import Conversation


async def create_conversation(
    pool: Pool,
    *,
    project_id: UUID,
    title: str = "Untitled",
) -> Conversation:
    row = await pool.fetchrow(queries.INSERT, project_id, title)
    return Conversation.from_record(row)


async def get_conversation(pool: Pool, conversation_id: UUID) -> Conversation | None:
    row = await pool.fetchrow(queries.GET, conversation_id)
    return Conversation.from_record(row) if row else None


async def list_conversations_by_project(pool: Pool, project_id: UUID) -> list[Conversation]:
    rows = await pool.fetch(queries.LIST_BY_PROJECT, project_id)
    return [Conversation.from_record(r) for r in rows]


async def delete_conversation(pool: Pool, conversation_id: UUID) -> None:
    await pool.execute(queries.DELETE, conversation_id)


async def update_title(pool: Pool, conversation_id: UUID, *, title: str) -> Conversation | None:
    """Rename a conversation. Returns the updated row or ``None`` if it
    no longer exists. Caller is responsible for trim/length validation;
    this just writes the SQL.
    """
    row = await pool.fetchrow(queries.UPDATE_TITLE, conversation_id, title)
    return Conversation.from_record(row) if row else None


async def add_tokens(
    pool: Pool,
    conversation_id: UUID,
    *,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float | Decimal = 0,
) -> Conversation | None:
    """Atomically add per-turn deltas to the conversation's running totals.

    Caller is responsible for zero/negative guards — this just executes
    the SQL. ``cost_usd`` is added the same atomic way the token deltas
    are; passing 0 (the default) leaves the cost column untouched.

    Returns the updated row, or ``None`` if the conversation no longer
    exists (caller should treat as a no-op in that case).
    """
    row = await pool.fetchrow(
        queries.ADD_TOKENS,
        conversation_id,
        input_tokens,
        output_tokens,
        Decimal(str(cost_usd)),
    )
    return Conversation.from_record(row) if row else None


async def reset_after_clear(pool: Pool, conversation_id: UUID) -> Conversation | None:
    """Zero token counters + message_count, bump last_active_at.

    Called by the messages-collection DELETE endpoint after the rows are
    truncated. Same transaction as the message DELETE to keep counts
    consistent.
    """
    row = await pool.fetchrow(queries.RESET_AFTER_CLEAR, conversation_id)
    return Conversation.from_record(row) if row else None
