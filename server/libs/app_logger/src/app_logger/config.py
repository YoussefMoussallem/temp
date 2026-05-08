"""Logger configuration model."""

from __future__ import annotations

from pydantic import BaseModel


class LoggerConfig(BaseModel, frozen=True):
    """Declarative configuration for :func:`app_logger.configure_logging`.

    Frozen so a single instance can be safely shared across modules. Services
    typically build this from environment variables at startup.

    Attributes:
        level: Root logger level (``"DEBUG"``, ``"INFO"``, ``"WARNING"``, ...).
        local_enabled: If ``True``, attach a :class:`LevelFileHandler` that
            writes to ``log_dir``. Disable in environments where only remote
            logging is desired.
        log_dir: Root directory for local log files. One subdirectory per UTC
            day is created underneath, with one file per log level.
        azure_enabled: If ``True``, attach an :class:`AzureBlobHandler`.
            Requires the ``azure`` extra (``pip install app-logger[azure]``).
        azure_connection_string: Azure Storage account connection string.
        azure_container_name: Blob container that receives the log files.
        azure_blob_prefix: Prefix prepended to every blob path, e.g. the
            service name, so multiple services can share one container.
        azure_batch_size: Flush the in-memory buffer once it holds this many
            records. Smaller values trade throughput for freshness.
        azure_flush_interval_seconds: Background thread also flushes on this
            cadence, so low-traffic services still ship logs promptly.
    """

    level: str = "INFO"

    # Local file logging
    local_enabled: bool = True
    log_dir: str = "logs"

    # Azure Blob Storage logging
    azure_enabled: bool = False
    azure_connection_string: str = ""
    azure_container_name: str = "logs"
    azure_blob_prefix: str = "app"
    azure_batch_size: int = 100
    azure_flush_interval_seconds: int = 30
