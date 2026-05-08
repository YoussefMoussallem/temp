"""Read-only settings endpoints — surface admin-managed config to authenticated callers.

Admins set the values via the ``admin/settings/*`` endpoints
(``app/routers/admin.py``); regular users (and the backend, on every
``/turn``) read them here. Auth is the regular ``get_current_user``
gate — any authenticated user can see which models the deployment is
configured to use, same trust level as today's
``GET /api/agent/models``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.db import Pool, get_pool
from app.db.app_settings.repository import get_all_settings as get_all_app_settings
from app.dependencies import CurrentUser, get_current_user

router = APIRouter(prefix="/settings", tags=["settings"])

_MODEL_SETTING_KEYS = ("default_model", "search_model", "export_model", "title_model")


def _as_str(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


@router.get("/models")
async def get_model_settings(_: CurrentUser = Depends(get_current_user)):
    """Return the admin-set main / search / export / title model defaults.

    Empty string for a key means "no admin default set yet" — the
    backend treats that as "fall back to env" for ``default_model``
    and as "fall back to main-loop model" for ``search_model`` /
    ``export_model`` / ``title_model``.
    """
    pool: Pool = await get_pool()
    settings_map = await get_all_app_settings(pool)
    return {key: _as_str(settings_map.get(key)) for key in _MODEL_SETTING_KEYS}
