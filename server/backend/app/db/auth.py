"""Auth — token validation via the db-service.

Client only — no FE proxy here because the frontend talks to the auth
provider directly (Firebase), not through us.
"""

from __future__ import annotations

import httpx

from ._shared import _get_base_url


async def validate_token(authorization: str) -> dict | None:
    """Ask the DB service to validate a bearer token.

    Returns a user-info dict on success, ``None`` on any failure
    (network, 401, 403, etc.). Callers should treat ``None`` as
    "not authenticated" without inspecting why. Used by components
    that need the DB service's view of the user (e.g. to confirm the
    user row exists) rather than just the JWT claims we validated
    locally in ``app.dependencies``.
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{_get_base_url()}/api/auth/validate",
                headers={"Authorization": authorization},
            )
            resp.raise_for_status()
            return resp.json()
    except Exception:
        return None
