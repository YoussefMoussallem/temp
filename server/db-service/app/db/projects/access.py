"""Access checks for project-scoped resources.

Every project-scoped router (projects, conversations, messages, slides)
calls ``require_project_access`` to enforce role-based authorization.

Role rank
---------
- ``viewer``  → can read project + conversations + messages + slides
- ``editor``  → viewer + can mutate conversations / messages / slides
- ``owner``   → editor + can rename / delete project + manage members

Returning 404 (not 403) when the caller has no membership is intentional:
it doesn't leak whether a project exists to a user who can't see it.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException

from app.db import Pool
from app.db.project_members.repository import get_role
from app.dependencies import CurrentUser

ROLE_RANK = {"viewer": 0, "editor": 1, "owner": 2}


def role_meets(role: str, *, min_role: str) -> bool:
    """True iff ``role`` is at least as privileged as ``min_role``."""
    return ROLE_RANK.get(role, -1) >= ROLE_RANK[min_role]


async def get_project_access(
    pool: Pool, project_id: UUID, user_id: str
) -> str | None:
    """Return the caller's role on the project, or None if no membership."""
    return await get_role(pool, project_id, user_id)


async def require_project_access(
    pool: Pool,
    project_id: UUID,
    user: CurrentUser,
    *,
    min_role: str = "viewer",
) -> str:
    """Raise 404 if the caller has no membership; 403 if their role is too low.

    Returns the caller's role string on success so the router can use it
    (e.g. to gate UI fields in the response).
    """
    role = await get_project_access(pool, project_id, user.azure_oid)
    if role is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if not role_meets(role, min_role=min_role):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return role
