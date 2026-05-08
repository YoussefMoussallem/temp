"""Alembic environment — builds DSN from POSTGRES_* env vars."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool, MetaData

from app.db.config import PostgresConfig

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = MetaData()

pg_cfg = PostgresConfig()
# Build the DSN once — used directly by both code paths below. We
# deliberately do NOT call ``config.set_main_option("sqlalchemy.url",
# ...)`` because that routes the value through ConfigParser, which
# treats ``%`` as interpolation syntax. URL-encoded password
# characters (e.g. the ``@`` in a UPN becomes ``%40``) and Entra
# bearer tokens contain ``%`` and would crash with
# ``ValueError: invalid interpolation syntax``.
_DSN = pg_cfg.sync_connection_dsn


def run_migrations_offline() -> None:
    context.configure(url=_DSN, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(_DSN, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
