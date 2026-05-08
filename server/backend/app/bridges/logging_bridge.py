"""Logging initialisation bridge — wires app_logger to application settings.

``app_logger`` is a generic, stand-alone logging package that knows how
to emit to stdout + rotating files + an Azure Blob sink. It does not
know about this app's settings model. This bridge is the single place
that reads ``settings.logging`` and hands it to ``app_logger`` as a
``LoggerConfig``.

Call ``init_logging()`` exactly once at process startup, before anything
else emits a log line (see ``app.main.create_app``).
"""

from __future__ import annotations

from app_logger import configure_logging
from app_logger.config import LoggerConfig
from app.config import get_settings


def init_logging() -> None:
    """Configure the root logger from application settings.

    Safe to call before other imports emit log records; subsequent
    ``logging.getLogger(...)`` / ``app_logger.get_logger(...)`` calls
    will use the configured handlers.
    """
    s = get_settings().logging
    configure_logging(
        LoggerConfig(
            level=s.level,
            local_enabled=s.local_enabled,
            log_dir=s.log_dir,
            azure_enabled=s.azure_enabled,
            azure_connection_string=s.azure_connection_string.get_secret_value(),
            azure_container_name=s.azure_container_name,
            azure_blob_prefix=s.azure_blob_prefix,
            azure_batch_size=s.azure_batch_size,
            azure_flush_interval_seconds=s.azure_flush_interval_seconds,
        )
    )
