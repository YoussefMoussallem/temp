"""Parameterized SQL queries for the project_members table."""

INSERT = """
    INSERT INTO project_members (user_id, project_id, role)
    VALUES ($1, $2, $3)
    RETURNING user_id, project_id, role, joined_at
"""

GET = """
    SELECT user_id, project_id, role, joined_at
    FROM project_members
    WHERE project_id = $1 AND user_id = $2
"""

GET_ROLE = """
    SELECT role
    FROM project_members
    WHERE project_id = $1 AND user_id = $2
"""

LIST_VIEWS_BY_PROJECT = """
    SELECT pm.user_id, pm.project_id, pm.role, pm.joined_at,
           u.email, u.display_name
    FROM project_members pm
    JOIN users u ON u.azure_oid = pm.user_id
    WHERE pm.project_id = $1
    ORDER BY
        CASE pm.role WHEN 'owner' THEN 0 WHEN 'editor' THEN 1 ELSE 2 END,
        pm.joined_at ASC
"""

LIST_USER_IDS_BY_PROJECT = """
    SELECT user_id
    FROM project_members
    WHERE project_id = $1
"""

UPDATE_ROLE = """
    UPDATE project_members
    SET role = $3
    WHERE project_id = $1 AND user_id = $2
    RETURNING user_id, project_id, role, joined_at
"""

DELETE = """
    DELETE FROM project_members
    WHERE project_id = $1 AND user_id = $2
"""

# Used by transfer-ownership: insert a new owner row, or upgrade the
# new owner's existing row (e.g. they were an editor) to owner.
UPSERT_AS_OWNER = """
    INSERT INTO project_members (user_id, project_id, role)
    VALUES ($1, $2, 'owner')
    ON CONFLICT (user_id, project_id) DO UPDATE SET role = 'owner'
    RETURNING user_id, project_id, role, joined_at
"""

# Used by transfer-ownership: demote the previous owner to editor so
# they keep access. Scoped to a specific user_id (we know who the old
# owner was from ``projects.user_id`` before the swap).
DEMOTE_OWNER_TO_EDITOR = """
    UPDATE project_members
    SET role = 'editor'
    WHERE project_id = $1 AND user_id = $2 AND role = 'owner'
"""
