"""PostgreSQL connection configuration."""

from __future__ import annotations

from urllib.parse import quote

from pydantic import PrivateAttr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.db.azure_auth import ManagedIdentityTokenProvider, POSTGRES_SCOPE


class PostgresConfig(BaseSettings):
    """Connection parameters loaded from environment variables.

    Env vars (prefix ``POSTGRES_``):
        POSTGRES_HOST, POSTGRES_PORT, POSTGRES_USER,
        POSTGRES_PASSWORD, POSTGRES_DATABASE, POSTGRES_DSN,
        POSTGRES_MIN_POOL_SIZE, POSTGRES_MAX_POOL_SIZE,
        POSTGRES_USE_ENTRA_AUTH, POSTGRES_ENTRA_CLIENT_ID
    """

    model_config = SettingsConfigDict(
        env_prefix="POSTGRES_",
        env_file=".env",
        extra="ignore",
    )

    host: str = "localhost"
    port: int = 5432
    user: str = "postgres"
    password: str = ""
    database: str = "edwin"
    dsn: str = ""

    min_pool_size: int = 2
    max_pool_size: int = 10
    use_entra_auth: bool = False
    entra_client_id: str = ""
    ssl: bool = False

    _token_provider: ManagedIdentityTokenProvider | None = PrivateAttr(default=None)

    @property
    def connection_dsn(self) -> str:
        """Return an explicit DSN or build one from components."""
        if self.dsn:
            return self.dsn
        user = quote(self.user, safe="")
        if self.use_entra_auth:
            return f"postgresql://{user}@{self.host}:{self.port}/{self.database}"
        password = quote(self.password, safe="")
        return f"postgresql://{user}:{password}@{self.host}:{self.port}/{self.database}"

    @property
    def sync_connection_dsn(self) -> str:
        """Return a psycopg2-compatible DSN for Alembic."""
        if self.dsn and not self.use_entra_auth:
            return self.dsn.replace("postgresql://", "postgresql+psycopg2://", 1)
        user = quote(self.user, safe="")
        if self.use_entra_auth:
            token = quote(self.get_entra_token(), safe="")
            return (
                f"postgresql+psycopg2://{user}:{token}"
                f"@{self.host}:{self.port}/{self.database}?sslmode=require"
            )
        password = quote(self.password, safe="")
        sslmode = "?sslmode=require" if self.ssl else ""
        return (
            f"postgresql+psycopg2://{user}:{password}"
            f"@{self.host}:{self.port}/{self.database}{sslmode}"
        )

    def get_entra_token(self) -> str:
        """Return an Azure Database for PostgreSQL Entra token."""
        if self._token_provider is None:
            self._token_provider = ManagedIdentityTokenProvider(
                scope=POSTGRES_SCOPE,
                client_id=self.entra_client_id,
            )
        return self._token_provider.get_token()
