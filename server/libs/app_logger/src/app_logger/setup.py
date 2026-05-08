"""Logging setup — configure the root logger and expose helper functions.

The public surface of ``app_logger`` is intentionally tiny:

- :func:`configure_logging` — call once at service startup.
- :func:`get_logger` — thin alias for :func:`logging.getLogger`.
- :func:`flush_all` — call before shutdown to drain buffered Azure logs.

No console handler is ever attached: this project treats logs as files/blobs,
not as stdout noise, so captured container output stays readable.
"""

from __future__ import annotations

import logging

from app_logger.config import LoggerConfig
from app_logger.formatter import JsonFormatter
from app_logger.handlers.local import LevelFileHandler
from app_logger.handlers.azure_blob import AzureBlobHandler


def configure_logging(config: LoggerConfig) -> None:
    """Configure the root logger with handlers derived from *config*.

    Any existing handlers on the root logger are closed and removed first,
    which makes this safe to call repeatedly (tests, hot-reload, process
    restart). Both handlers share a single :class:`JsonFormatter` instance.
    """
    root = logging.getLogger()
    root.setLevel(config.level)

    # Drop any handlers left behind by a previous call so we never end up
    # with duplicated log lines when the process is re-initialised.
    for handler in list(root.handlers):
        handler.close()
    root.handlers.clear()

    formatter = JsonFormatter()

    if config.local_enabled:
        local = LevelFileHandler(config.log_dir)
        local.setFormatter(formatter)
        root.addHandler(local)

    if config.azure_enabled:
        azure = AzureBlobHandler(
            connection_string=config.azure_connection_string,
            container=config.azure_container_name,
            prefix=config.azure_blob_prefix,
            batch_size=config.azure_batch_size,
            flush_interval_seconds=config.azure_flush_interval_seconds,
        )
        azure.setFormatter(formatter)
        root.addHandler(azure)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger.

    Thin alias for :func:`logging.getLogger` — exists so callers can import
    everything they need from a single module.
    """
    return logging.getLogger(name)


def flush_all() -> None:
    """Flush every handler on the root logger.

    Call from the application's shutdown hook. Matters mainly for
    :class:`AzureBlobHandler`, which otherwise only ships records on its
    background-thread cadence and would drop any final batch on exit.
    """
    for handler in logging.getLogger().handlers:
        handler.flush()
