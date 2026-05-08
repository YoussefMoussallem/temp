"""Parameterized SQL queries for the messages table."""

NEXT_SEQUENCE = """
    SELECT COALESCE(MAX(sequence), -1) + 1
    FROM messages
    WHERE conversation_id = $1
"""

INSERT = """
    INSERT INTO messages (conversation_id, sequence, role, content)
    VALUES ($1, $2, $3, $4::jsonb)
    RETURNING id, conversation_id, sequence, role, content, created_at
"""

BUMP_CONVERSATION = """
    UPDATE conversations
    SET message_count = message_count + 1,
        last_active_at = now()
    WHERE id = $1
"""

LIST_BY_CONVERSATION = """
    SELECT id, conversation_id, sequence, role, content, created_at
    FROM messages
    WHERE conversation_id = $1
    ORDER BY sequence ASC
"""

LIST_BEFORE_SEQUENCE = """
    SELECT id, conversation_id, sequence, role, content, created_at
    FROM messages
    WHERE conversation_id = $1 AND sequence < $2
    ORDER BY sequence DESC
    LIMIT $3
"""

DELETE_ALL_FOR_CONVERSATION = """
    DELETE FROM messages WHERE conversation_id = $1
"""
