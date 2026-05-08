"""Parameterized SQL queries for the usage_records table.

All queries use positional $N placeholders — values are never interpolated
into the SQL string.
"""

INSERT_RECORD = """
    INSERT INTO usage_records (user_id, model, input_tokens, output_tokens, cost_usd)
    VALUES ($1, $2, $3, $4, $5)
    RETURNING id, user_id, model, input_tokens, output_tokens, cost_usd, recorded_at
"""

SELECT_FOR_USER = """
    SELECT id, user_id, model, input_tokens, output_tokens, cost_usd, recorded_at
    FROM usage_records
    WHERE user_id = $1
      AND recorded_at >= $2
      AND recorded_at <= $3
    ORDER BY recorded_at DESC
"""

TOTALS_FOR_USER = """
    SELECT
        model,
        COUNT(*)::int            AS record_count,
        SUM(input_tokens)::int   AS total_input_tokens,
        SUM(output_tokens)::int  AS total_output_tokens,
        SUM(cost_usd)            AS total_cost_usd
    FROM usage_records
    WHERE user_id = $1
      AND recorded_at >= $2
      AND recorded_at <= $3
    GROUP BY model
    ORDER BY total_cost_usd DESC
"""

ALL_USER_TOTALS = """
    SELECT
        u.azure_oid              AS user_id,
        u.email,
        u.display_name,
        COUNT(*)::int            AS record_count,
        SUM(ur.input_tokens)::int  AS total_input_tokens,
        SUM(ur.output_tokens)::int AS total_output_tokens,
        SUM(ur.cost_usd)          AS total_cost_usd
    FROM usage_records ur
    JOIN users u ON u.azure_oid = ur.user_id
    WHERE ur.recorded_at >= $1
      AND ur.recorded_at <= $2
    GROUP BY u.azure_oid, u.email, u.display_name
    ORDER BY total_cost_usd DESC
"""

ALL_RECORDS_WITH_USER = """
    SELECT
        ur.id,
        ur.user_id,
        u.email,
        u.display_name,
        ur.model,
        ur.input_tokens,
        ur.output_tokens,
        ur.cost_usd,
        ur.recorded_at
    FROM usage_records ur
    JOIN users u ON u.azure_oid = ur.user_id
    WHERE ur.recorded_at >= $1
      AND ur.recorded_at <= $2
    ORDER BY ur.recorded_at DESC
"""

AGGREGATE_STATS = """
    SELECT
        COUNT(DISTINCT ur.user_id)::int           AS total_users,
        COUNT(*)::int                             AS total_records,
        COALESCE(SUM(ur.input_tokens), 0)::bigint AS total_input_tokens,
        COALESCE(SUM(ur.output_tokens), 0)::bigint AS total_output_tokens,
        COALESCE(SUM(ur.cost_usd), 0)             AS total_cost_usd
    FROM usage_records ur
    WHERE ur.recorded_at >= $1
      AND ur.recorded_at <= $2
"""
