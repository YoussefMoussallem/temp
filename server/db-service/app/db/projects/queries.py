"""Parameterized SQL queries for the projects table."""

INSERT = """
    INSERT INTO projects (user_id, name, description)
    VALUES ($1, $2, $3)
    RETURNING id, user_id, name, description, created_at, updated_at
"""

GET = """
    SELECT id, user_id, name, description, created_at, updated_at
    FROM projects
    WHERE id = $1
"""

LIST_BY_USER = """
    SELECT p.id, p.user_id, p.name, p.description,
           p.created_at, p.updated_at, pm.role
    FROM projects p
    JOIN project_members pm ON pm.project_id = p.id
    WHERE pm.user_id = $1
    ORDER BY p.updated_at DESC
"""

UPDATE = """
    UPDATE projects
    SET name = COALESCE($2, name),
        description = COALESCE($3, description),
        updated_at = now()
    WHERE id = $1
    RETURNING id, user_id, name, description, created_at, updated_at
"""

DELETE = """
    DELETE FROM projects WHERE id = $1
"""

# Admin-only: every project in the system, with the owner's email, the
# member count, and lifetime token totals (summed across all the
# project's conversations).
#
# Two LEFT JOINs:
#   * project_members → counts members
#   * conversations    → sums token columns from migration 0005
# Both LEFTs so a project with zero members or zero conversations still
# appears (defensively — owner is always a member, but conversations
# can be empty).
LIST_ALL_WITH_STATS = """
    SELECT
        p.id, p.user_id, p.name, p.description,
        p.created_at, p.updated_at,
        u.email AS owner_email,
        u.display_name AS owner_display_name,
        COALESCE(mem.member_count, 0)::int AS member_count,
        COALESCE(conv.total_input_tokens, 0)::bigint AS total_input_tokens,
        COALESCE(conv.total_output_tokens, 0)::bigint AS total_output_tokens,
        COALESCE(conv.total_cost_usd, 0)             AS total_cost_usd,
        COALESCE(conv.conversation_count, 0)::int AS conversation_count
    FROM projects p
    JOIN users u ON u.azure_oid = p.user_id
    LEFT JOIN (
        SELECT project_id, COUNT(*) AS member_count
        FROM project_members
        GROUP BY project_id
    ) mem ON mem.project_id = p.id
    LEFT JOIN (
        SELECT project_id,
               SUM(total_input_tokens)  AS total_input_tokens,
               SUM(total_output_tokens) AS total_output_tokens,
               SUM(total_cost_usd)      AS total_cost_usd,
               COUNT(*)                 AS conversation_count
        FROM conversations
        GROUP BY project_id
    ) conv ON conv.project_id = p.id
    ORDER BY p.updated_at DESC
"""

# Step 1 of transfer-ownership: change the denormalized owner pointer.
# Steps 2 and 3 (member-row updates) live in
# ``project_members.queries`` so all member writes share one file.
TRANSFER_OWNER = """
    UPDATE projects
    SET user_id    = $2,
        updated_at = now()
    WHERE id = $1
    RETURNING id, user_id, name, description, created_at, updated_at
"""
