"""Local-file log handler: per-day, per-level log files under a root directory."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import IO


class LevelFileHandler(logging.Handler):
    """Write log records to ``{log_dir}/{YYYY-MM-DD}/{level}.log``.

    One file is kept open per ``(date, level)`` combination so writes don't
    pay the cost of opening/closing a handle per record. When the UTC date
    rolls over, yesterday's handles are closed and a fresh set is opened on
    demand — no background thread, no scheduler.

    The handler is thread-safe: a single lock serialises the rollover and
    write path, which is plenty for logging throughput (I/O dominates).
    """

    def __init__(self, log_dir: str) -> None:
        """Initialise the handler.

        ``log_dir`` is resolved lazily: the directory is created on first
        write, not here, so importing this module never touches the disk.
        """
        super().__init__()
        self._log_dir = Path(log_dir)
        self._lock = threading.Lock()
        self._handles: dict[tuple[str, str], IO[str]] = {}
        self._current_date: str = ""

    # ── internal helpers ─────────────────────────────────────────────

    def _date_str(self, record: logging.LogRecord) -> str:
        """Return the UTC date of *record* as ``YYYY-MM-DD``.

        UTC is used deliberately: log files must have a stable ordering
        regardless of host timezone or DST transitions.
        """
        return datetime.fromtimestamp(record.created, tz=timezone.utc).strftime("%Y-%m-%d")

    def _rollover_if_needed(self, date_str: str) -> None:
        """Close open handles when the UTC date changes.

        Called on every emit but short-circuits in the common case where the
        date is unchanged. Close failures are swallowed — we can't do
        anything useful with them inside the logging path.
        """
        if date_str == self._current_date:
            return
        for fh in self._handles.values():
            try:
                fh.close()
            except Exception:
                pass
        self._handles.clear()
        self._current_date = date_str

    def _get_handle(self, date_str: str, level: str) -> IO[str]:
        """Return (or lazily open) the append-mode handle for a date/level pair."""
        key = (date_str, level)
        if key not in self._handles:
            day_dir = self._log_dir / date_str
            day_dir.mkdir(parents=True, exist_ok=True)
            self._handles[key] = open(day_dir / f"{level}.log", "a", encoding="utf-8")
        return self._handles[key]

    # ── logging.Handler interface ────────────────────────────────────

    def emit(self, record: logging.LogRecord) -> None:
        """Write *record* to the appropriate file.

        A trailing blank line separates records so the block format rendered
        by :class:`JsonFormatter` stays visually distinct. All exceptions are
        routed through :meth:`logging.Handler.handleError` so logging failures
        never propagate into the application.
        """
        try:
            date_str = self._date_str(record)
            level = record.levelname.lower()
            line = self.format(record) + "\n\n"
            with self._lock:
                self._rollover_if_needed(date_str)
                fh = self._get_handle(date_str, level)
                fh.write(line)
                # Flush per record so crashes don't lose the last few lines.
                # The throughput cost is acceptable for a service-level logger.
                fh.flush()
        except Exception:
            self.handleError(record)

    def close(self) -> None:
        """Close every open file handle and release the base-class resources."""
        with self._lock:
            for fh in self._handles.values():
                try:
                    fh.close()
                except Exception:
                    pass
            self._handles.clear()
        super().close()
