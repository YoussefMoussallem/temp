"""Parameterized SQL queries for the slides table."""

_COLUMNS = "id, project_id, position, title, html, created_at, updated_at"

INSERT = f"""
    INSERT INTO slides (project_id, position, title, html)
    VALUES ($1, $2, $3, $4)
    RETURNING {_COLUMNS}
"""

GET = f"""
    SELECT {_COLUMNS}
    FROM slides
    WHERE id = $1
"""

LIST_BY_PROJECT = f"""
    SELECT {_COLUMNS}
    FROM slides
    WHERE project_id = $1
    ORDER BY position
"""

UPDATE = f"""
    UPDATE slides
    SET html = COALESCE($2, html),
        title = COALESCE($3, title),
        updated_at = now()
    WHERE id = $1
    RETURNING {_COLUMNS}
"""

DELETE = "DELETE FROM slides WHERE id = $1"

# Open a gap at `position` (inclusive) by shifting existing slides down.
SHIFT_DOWN_FROM = """
    UPDATE slides
    SET position = position + 1, updated_at = now()
    WHERE project_id = $1 AND position >= $2
"""

# Close a gap left at `position` (exclusive) by shifting later slides up.
SHIFT_UP_FROM = """
    UPDATE slides
    SET position = position - 1, updated_at = now()
    WHERE project_id = $1 AND position > $2
"""

# Renumber one slide. Used by reorder.
SET_POSITION = """
    UPDATE slides
    SET position = $2, updated_at = now()
    WHERE id = $1
"""
