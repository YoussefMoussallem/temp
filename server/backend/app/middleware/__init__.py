"""HTTP middleware stack for the Edwin backend.

Three concerns, three modules:

* ``request_context``   — request-id contextvar + end-of-response
  access logging. Implemented as raw ASGI middleware so it does not
  buffer SSE response bodies.
* ``exception_handler`` — catch-all handler for unhandled
  ``Exception`` raised before the response starts. ``HTTPException``
  and validation errors keep FastAPI's defaults.
* ``rate_limit``        — per-IP rate limiting via SlowAPI with
  in-memory storage. Single-replica only (see docstring inside).

``main.py`` wires all three in via the ``register_*`` helpers and the
``RequestContextMiddleware`` class.
"""

from .exception_handler import register_exception_handlers
from .rate_limit import limiter, register_rate_limiting
from .request_context import RequestContextMiddleware, get_request_id

__all__ = [
    "RequestContextMiddleware",
    "get_request_id",
    "limiter",
    "register_exception_handlers",
    "register_rate_limiting",
]
