"""Parameterized SQL queries for the memory tables.

Two scopes mean two query sets that mirror each other; we keep them
side-by-side here rather than abstracting because the column lists
differ (project memories carry ``created_by_user_id``) and the
abstraction wouldn't pay for itself at two callers.

Upserts use ``ON CONFLICT`` on the scope-+-slug unique constraint —
re-saving the same slug overwrites in place, which is the common case
when the user changes their mind (or the model refines an entry).
"""

# ── user_memories ──────────────────────────────────────────────────────────
_USER_COLUMNS = "id, user_id, slug, type, name, description, body, created_at, updated_at"

USER_LIST = f"""
    SELECT {_USER_COLUMNS}
    FROM user_memories
    WHERE user_id = $1
    ORDER BY updated_at DESC
"""

USER_GET = f"""
    SELECT {_USER_COLUMNS}
    FROM user_memories
    WHERE user_id = $1 AND slug = $2
"""

# Upsert by (user_id, slug). Updates every mutable field on conflict so
# the model can refine an existing memory without first reading it.
USER_UPSERT = f"""
    INSERT INTO user_memories (user_id, slug, type, name, description, body)
    VALUES ($1, $2, $3, $4, $5, $6)
    ON CONFLICT (user_id, slug) DO UPDATE
       SET type        = EXCLUDED.type,
           name        = EXCLUDED.name,
           description = EXCLUDED.description,
           body        = EXCLUDED.body,
           updated_at  = now()
    RETURNING {_USER_COLUMNS}
"""

USER_DELETE = """
    DELETE FROM user_memories
    WHERE user_id = $1 AND slug = $2
"""


# ── project_memories ───────────────────────────────────────────────────────
_PROJECT_COLUMNS = (
    "id, project_id, slug, type, name, description, body, "
    "created_by_user_id, created_at, updated_at"
)

PROJECT_LIST = f"""
    SELECT {_PROJECT_COLUMNS}
    FROM project_memories
    WHERE project_id = $1
    ORDER BY updated_at DESC
"""

PROJECT_GET = f"""
    SELECT {_PROJECT_COLUMNS}
    FROM project_memories
    WHERE project_id = $1 AND slug = $2
"""

# Upsert by (project_id, slug). ``created_by_user_id`` is preserved on
# update — the original author keeps the attribution even when the row
# is later refined (whether by them or by another collaborator).
PROJECT_UPSERT = f"""
    INSERT INTO project_memories
        (project_id, slug, type, name, description, body, created_by_user_id)
    VALUES ($1, $2, $3, $4, $5, $6, $7)
    ON CONFLICT (project_id, slug) DO UPDATE
       SET type        = EXCLUDED.type,
           name        = EXCLUDED.name,
           description = EXCLUDED.description,
           body        = EXCLUDED.body,
           updated_at  = now()
    RETURNING {_PROJECT_COLUMNS}
"""

PROJECT_DELETE = """
    DELETE FROM project_memories
    WHERE project_id = $1 AND slug = $2
"""
