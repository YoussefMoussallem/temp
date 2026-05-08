"""Parameterized SQL for ``app_settings`` (key/value config).

All values are stored as JSONB so the same schema can hold strings
today and richer shapes later without a migration.
"""

GET_BY_KEY = """
    SELECT key, value, updated_at, updated_by
    FROM app_settings
    WHERE key = $1
"""

GET_BY_KEYS = """
    SELECT key, value, updated_at, updated_by
    FROM app_settings
    WHERE key = ANY($1::varchar[])
"""

GET_ALL = """
    SELECT key, value, updated_at, updated_by
    FROM app_settings
    ORDER BY key
"""

# Upsert. ``updated_by`` defaults to NULL when the caller doesn't
# supply one (e.g. an internal bootstrap), and ``updated_at`` is
# refreshed by the trigger-free explicit ``now()`` so we don't depend
# on a row-level trigger being installed.
UPSERT = """
    INSERT INTO app_settings (key, value, updated_at, updated_by)
    VALUES ($1, $2::jsonb, now(), $3)
    ON CONFLICT (key) DO UPDATE
        SET value      = EXCLUDED.value,
            updated_at = now(),
            updated_by = EXCLUDED.updated_by
    RETURNING key, value, updated_at, updated_by
"""
