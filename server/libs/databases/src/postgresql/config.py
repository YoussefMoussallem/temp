"""PostgreSQL connection configuration."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class PostgresConfig(BaseSettings):
    """Settings for the shared :class:`Pool`, populated from env / ``.env``.

    All fields are sourced from ``POSTGRES_*`` environment variables (e.g.
    ``POSTGRES_HOST``) or a ``.env`` file at the project root. Unknown keys
    are ignored so the same ``.env`` can be shared across services.

    Attributes:
        host / port / user / password / database: Individual connection
            components, used to build a DSN if ``dsn`` is not set.
        dsn: Optional pre-built DSN. When provided (e.g. for managed Postgres
            services that hand out a full connection URL), it overrides the
            component fields entirely.
        min_pool_size: Minimum connections asyncpg keeps warm. Too low and
            burst traffic pays TCP/TLS setup costs; too high wastes server
            slots.
        max_pool_size: Hard ceiling on concurrent connections. Must be set
            below Postgres' own ``max_connections`` minus whatever other
            services share the database.
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

    @property
    def connection_dsn(self) -> str:
        """Return the DSN asyncpg should connect with.

        An explicit ``dsn`` wins if present (it may carry query-string options
        the component fields cannot express); otherwise one is assembled from
        host/port/user/password/database.
        """
        if self.dsn:
            return self.dsn
        return (
            f"postgresql://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.database}"
        )
