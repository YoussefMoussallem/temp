"""Parameterized SQL queries for the conversations table."""

_RETURN_COLS = (
    "id, project_id, title, created_at, last_active_at, message_count, "
    "total_input_tokens, total_output_tokens, total_cost_usd"
)

INSERT = f"""
    INSERT INTO conversations (project_id, title)
    VALUES ($1, $2)
    RETURNING {_RETURN_COLS}
"""

GET = f"""
    SELECT {_RETURN_COLS}
    FROM conversations
    WHERE id = $1
"""

LIST_BY_PROJECT = f"""
    SELECT {_RETURN_COLS}
    FROM conversations
    WHERE project_id = $1
    ORDER BY last_active_at DESC
"""

DELETE = """
    DELETE FROM conversations WHERE id = $1
"""

# Title-only PATCH. Bumps last_active_at so a freshly-renamed conversation
# floats to the top of the project's list (same ordering rule as ADD_TOKENS
# / RESET_AFTER_CLEAR — last activity wins). title is required at the
# router layer; this query trusts that and just writes whatever it's given.
UPDATE_TITLE = f"""
    UPDATE conversations
    SET title          = $2,
        last_active_at = now()
    WHERE id = $1
    RETURNING {_RETURN_COLS}
"""

# Atomic add — caller passes deltas, never absolute values, so concurrent
# turns can both contribute without lost updates. ``$4`` is cost in USD,
# computed by the backend via ``litellm_bridge.calculate_cost`` from the
# same model + token deltas being recorded here. Rounded to 8 decimal
# places to match ``usage_records.cost_usd`` precision.
ADD_TOKENS = f"""
    UPDATE conversations
    SET total_input_tokens  = total_input_tokens  + $2,
        total_output_tokens = total_output_tokens + $3,
        total_cost_usd      = total_cost_usd      + $4,
        last_active_at      = now()
    WHERE id = $1
    RETURNING {_RETURN_COLS}
"""

# Used by /clear: zero out counters + cost + message_count, bump
# last_active_at so the project's conversation list ordering still
# reflects the action.
RESET_AFTER_CLEAR = f"""
    UPDATE conversations
    SET total_input_tokens  = 0,
        total_output_tokens = 0,
        total_cost_usd      = 0,
        message_count       = 0,
        last_active_at      = now()
    WHERE id = $1
    RETURNING {_RETURN_COLS}
"""
