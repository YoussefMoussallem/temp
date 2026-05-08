"""Azure managed identity token helpers for Postgres and Redis."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from threading import Lock

from azure.identity import DefaultAzureCredential

logger = logging.getLogger(__name__)

POSTGRES_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"
REDIS_SCOPE = "https://redis.azure.com/.default"


class ManagedIdentityTokenProvider:
    """Small cached token provider for Azure-hosted services."""

    def __init__(self, *, scope: str, client_id: str = "") -> None:
        self._scope = scope
        self._credential = DefaultAzureCredential(
            managed_identity_client_id=client_id or None,
            exclude_interactive_browser_credential=True,
        )
        self._token: str | None = None
        self._expires_at: datetime | None = None
        self._lock = Lock()
        self._refresh_buffer = timedelta(minutes=5)

    def get_token(self) -> str:
        """Return a valid access token, refreshing before expiry."""
        with self._lock:
            now = datetime.utcnow()
            if (
                self._token is None
                or self._expires_at is None
                or now >= self._expires_at - self._refresh_buffer
            ):
                token = self._credential.get_token(self._scope)
                self._token = token.token
                self._expires_at = datetime.utcfromtimestamp(token.expires_on)
                logger.debug("Refreshed Azure token for scope %s", self._scope)
            return self._token
