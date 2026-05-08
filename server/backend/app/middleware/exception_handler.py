"""Global handler for unhandled exceptions.

Scope of this handler
---------------------
Only fires for bare ``Exception`` raised from a handler *before* the
response starts. The following are intentionally **not** intercepted:

* ``HTTPException``                — FastAPI's default already returns
  ``{"detail": ...}`` with the right status code.
* ``RequestValidationError``       — FastAPI's default returns 422
  with field-level error info, which the frontend uses.
* ``slowapi.errors.RateLimitExceeded`` — SlowAPI's own handler
  produces a 429 with a ``Retry-After`` header.

Streaming endpoints (e.g. ``/api/agent/turn``) catch their own errors
inside the generator and yield an SSE ``error`` event — the response
has already started by then so this handler can't intercept anyway.
That's the correct behaviour: status 200 + a structured ``error``
event in-band, instead of a torn 500.

Why this exists
---------------
Without it, an unexpected ``Exception`` produces FastAPI's default
``"Internal Server Error"`` plain-text body and the stack trace lands
on stderr with no request-context. With it, we get a stable JSON
shape on the wire (frontend doesn't have to content-type-sniff 5xx)
and the trace is logged with method + path + the request-id from
``RequestContextMiddleware`` so it's correlatable across log lines.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app_logger import get_logger

from .request_context import get_request_id

logger = get_logger(__name__)


async def _unhandled_exception_handler(
    request: Request, exc: Exception,
) -> JSONResponse:
    """Log the trace with request context, return a stable JSON 500."""
    req_id = get_request_id()
    logger.exception(
        "Unhandled exception on %s %s (req_id=%s): %s",
        request.method,
        request.url.path,
        req_id,
        exc,
    )
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "request_id": req_id or None,
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Wire the catch-all ``Exception`` handler onto the app.

    HTTPException / RequestValidationError / RateLimitExceeded keep
    their default handlers (see module docstring).
    """
    app.add_exception_handler(Exception, _unhandled_exception_handler)
