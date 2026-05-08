"""Logging handlers — one sink per destination.

- :class:`LevelFileHandler` writes to local per-day, per-level files.
- :class:`AzureBlobHandler` batches records and ships them to Azure Blob
  Storage as append blobs.

Both are attached to the root logger by :func:`app_logger.configure_logging`
based on :class:`LoggerConfig`; users rarely need to import them directly.
"""

from app_logger.handlers.local import LevelFileHandler
from app_logger.handlers.azure_blob import AzureBlobHandler

__all__ = ["LevelFileHandler", "AzureBlobHandler"]
