"""Azure Blob Storage handler: batched, background-thread flushing."""

from __future__ import annotations

import logging
import threading
from collections import deque
from datetime import datetime, timezone


class AzureBlobHandler(logging.Handler):
    """Buffer log records in memory and append them to Azure Append Blobs.

    Design:

    * Records are kept in an in-memory :class:`~collections.deque` and flushed
      in batches to avoid a network round-trip per log line.
    * A daemon background thread flushes on a fixed cadence so low-traffic
      services still ship logs, even when the buffer never reaches
      ``batch_size``.
    * Blob layout mirrors :class:`LevelFileHandler`:
      ``{prefix}/{YYYY-MM-DD}/{level}.log`` — one append blob per UTC day per
      level, so the on-disk and in-blob views are easy to correlate.
    * All Azure exceptions are swallowed. Logging must never crash the
      application hosting it; losing a batch is preferable to taking down the
      request path.
    """

    def __init__(
        self,
        connection_string: str,
        container: str,
        prefix: str = "app",
        batch_size: int = 100,
        flush_interval_seconds: int = 30,
    ) -> None:
        """Start the background flush thread and open a blob service client.

        The client is constructed eagerly so that a bad connection string
        fails at startup rather than at the first log line.
        """
        super().__init__()
        self._container = container
        self._prefix = prefix
        self._batch_size = batch_size
        self._flush_interval = flush_interval_seconds

        self._service_client = self._make_client(connection_string)
        self._buffer: deque[logging.LogRecord] = deque()
        self._flush_lock = threading.Lock()
        self._stop = threading.Event()

        self._thread = threading.Thread(
            target=self._flush_loop, daemon=True, name="AzureBlobHandler"
        )
        self._thread.start()

    # ── setup ────────────────────────────────────────────────────────

    @staticmethod
    def _make_client(connection_string: str):
        """Construct a ``BlobServiceClient``, reporting a helpful error if the
        optional ``azure-storage-blob`` dependency is missing.

        The import lives inside the function so ``app_logger`` can be imported
        without the ``[azure]`` extra installed — services that only use
        local logging shouldn't need the Azure SDK on their path.
        """
        try:
            from azure.storage.blob import BlobServiceClient  # noqa: PLC0415
        except ImportError as exc:
            raise ImportError(
                "azure-storage-blob is required for Azure logging. "
                'Install with: pip install "app-logger[azure]"'
            ) from exc
        return BlobServiceClient.from_connection_string(connection_string)

    # ── background flush loop ────────────────────────────────────────

    def _flush_loop(self) -> None:
        """Flush every ``flush_interval`` seconds until :meth:`close` is called.

        :meth:`threading.Event.wait` returns ``True`` when the event is set,
        so the loop exits cleanly on shutdown without needing a separate
        sleep/interrupt dance.
        """
        while not self._stop.wait(self._flush_interval):
            self._flush()

    # ── core flush ───────────────────────────────────────────────────

    def _flush(self) -> None:
        """Drain the buffer and upload the records grouped by (date, level).

        Grouping happens outside the buffer lock so the hot path (``emit``)
        can keep appending while we're packaging the previous batch.
        """
        with self._flush_lock:
            if not self._buffer:
                return
            records = list(self._buffer)
            self._buffer.clear()

        # Grouped uploads minimise the number of append_block calls: one per
        # (date, level) slot rather than one per record.
        groups: dict[tuple[str, str], list[logging.LogRecord]] = {}
        for record in records:
            date_str = datetime.fromtimestamp(record.created, tz=timezone.utc).strftime("%Y-%m-%d")
            level = record.levelname.lower()
            groups.setdefault((date_str, level), []).append(record)

        for (date_str, level), recs in groups.items():
            blob_path = f"{self._prefix}/{date_str}/{level}.log"
            payload = "\n\n".join(self.format(r) for r in recs) + "\n\n"
            self._append_to_blob(blob_path, payload)

    def _append_to_blob(self, blob_path: str, data: str) -> None:
        """Append *data* to the target blob, creating it on first write.

        Append blobs must exist before ``append_block`` is called, so we
        attempt :meth:`create_append_blob` every time and tolerate the
        ``ResourceExistsError`` on subsequent writes — cheaper than a
        separate "does it exist?" check. Any other error is swallowed on
        purpose: the application must keep running even when Azure is down.
        """
        try:
            from azure.core.exceptions import ResourceExistsError  # noqa: PLC0415

            blob_client = self._service_client.get_blob_client(
                container=self._container, blob=blob_path
            )
            try:
                blob_client.create_append_blob()
            except ResourceExistsError:
                pass
            blob_client.append_block(data.encode("utf-8"))
        except Exception:
            # Best-effort: tracing/logging must never crash the application.
            pass

    # ── logging.Handler interface ────────────────────────────────────

    def emit(self, record: logging.LogRecord) -> None:
        """Append *record* to the buffer and flush early if it is full.

        The :class:`~collections.deque` append is atomic under the GIL, so no
        additional lock is needed on the hot path.
        """
        self._buffer.append(record)
        if len(self._buffer) >= self._batch_size:
            self._flush()

    def flush(self) -> None:
        """Flush synchronously (used by :func:`app_logger.flush_all`)."""
        self._flush()
        super().flush()

    def close(self) -> None:
        """Stop the background thread and flush one final time on shutdown."""
        self._stop.set()
        self._flush()
        super().close()
