"""Human-readable log formatter: aligned key/value lines."""

from __future__ import annotations

import json
import logging
from typing import Any
from datetime import datetime, timezone

# Standard LogRecord attributes: anything in this set is produced by the
# logging machinery itself and should NOT surface as a user-visible field.
# Everything else on ``record.__dict__`` is assumed to have come from the
# caller's ``extra={...}`` (or a LoggerAdapter) and is rendered as a field.
_RESERVED: frozenset[str] = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "message",
        "taskName",
    }
)


def _stringify(value: Any) -> str:
    """Render *value* as a single display string for the log block.

    Strings pass through unchanged; primitives use ``str()``; everything else
    is JSON-encoded with ``default=str`` so exotic types (datetimes, enums,
    dataclasses via ``asdict``, ...) still produce something readable rather
    than raising. A final ``str()`` fallback guarantees we never raise from
    inside a log call.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)) or value is None:
        return str(value)
    try:
        return json.dumps(value, default=str, ensure_ascii=False)
    except Exception:
        return str(value)


class JsonFormatter(logging.Formatter):
    """Format a LogRecord as a human-readable block.

    Output shape::

        [2026-04-24T12:00:00.123Z] INFO  app.api
          message  : request served
          path     : /chat
          status   : 200
          location : routes.py:42

    The class name is kept as ``JsonFormatter`` for backwards compatibility
    with existing imports; the output itself is NOT JSON. The block format
    wins here because log files are read by humans far more often than by
    machines, and the aligned ``key : value`` shape scans cleanly in a
    terminal without tooling.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Render *record* as an aligned multi-line block.

        Field order: ``message`` first, then any caller-supplied ``extra``
        keys in insertion order, then a synthetic ``location`` field pointing
        at the source site, then ``exception`` (full traceback) if present.
        Column width is computed per record so the ``:`` separators line up
        within each block.
        """
        record.message = record.getMessage()

        # ISO-8601 UTC timestamp trimmed to milliseconds — matches what most
        # log viewers expect and keeps output width predictable.
        ts = (
            datetime.fromtimestamp(record.created, tz=timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%S.%f"
            )[:-3]
            + "Z"
        )
        header = f"[{ts}] {record.levelname:<8} {record.name}"

        fields: list[tuple[str, str]] = [("message", record.message)]

        # Promote caller-supplied ``extra`` keys to fields. ``_RESERVED``
        # filters out logging's own attributes; the underscore check skips
        # any private fields a LoggerAdapter might have injected.
        for k, v in record.__dict__.items():
            if k in _RESERVED or k.startswith("_"):
                continue
            fields.append((k, _stringify(v)))

        fields.append(("location", f"{record.module}:{record.lineno}"))

        if record.exc_info:
            fields.append(("exception", self.formatException(record.exc_info)))

        # Align the ``:`` separator across every field in this block.
        width = max(len(k) for k, _ in fields)
        indent = " " * (2 + width + 3)  # "  " + key + " : "

        lines = [header]
        for key, value in fields:
            # Multi-line values (tracebacks, pretty JSON) are indented so
            # continuation lines sit under the value column, not the key.
            value_lines = value.splitlines() or [""]
            lines.append(f"  {key:<{width}} : {value_lines[0]}")
            for extra_line in value_lines[1:]:
                lines.append(f"{indent}{extra_line}")

        return "\n".join(lines)
