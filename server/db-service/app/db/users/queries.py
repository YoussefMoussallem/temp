"""Parameterized SQL queries for the users table.

All queries use positional $N placeholders — values are never interpolated
into the SQL string.
"""

UPSERT = """
    INSERT INTO users (azure_oid, email, display_name)
    VALUES ($1, $2, $3)
    ON CONFLICT (azure_oid) DO UPDATE
        SET email        = COALESCE(EXCLUDED.email, users.email),
            display_name = COALESCE(EXCLUDED.display_name, users.display_name)
    RETURNING azure_oid, email, display_name, created_at
"""

GET_BY_OID = """
    SELECT azure_oid, email, display_name, created_at
    FROM users
    WHERE azure_oid = $1
"""

GET_BY_EMAIL = """
    SELECT azure_oid, email, display_name, created_at
    FROM users
    WHERE email = $1
"""

GET_ALL = """
    SELECT azure_oid, email, display_name, created_at
    FROM users
    ORDER BY created_at DESC
"""

# Admin-only. ON DELETE CASCADE on users(azure_oid) covers everything
# downstream in one shot:
#   * usage_records      → deleted
#   * projects           → deleted (if user is the denormalized owner),
#                          which cascades to:
#       * conversations  → deleted
#       * messages       → deleted
#       * slides         → deleted
#       * project_members rows on those projects → deleted
#   * project_members where user is a non-owner → deleted directly
#
# Anything they merely *participated* in (a project owned by someone
# else where they were editor/viewer) stays — only their membership row
# is removed by the project_members FK cascade.
DELETE_USER = """
    DELETE FROM users WHERE azure_oid = $1
"""
