"""DB-service surface — typed Python client + FE HTTP proxy.

Why both live here
------------------
``app/db/`` owns every interaction with the separate db-service
microservice. Two surfaces exist:

  * **Typed Python client** — used by backend code (agent tools,
    services, route handlers). Each domain file exposes the relevant
    functions (e.g. ``slides.create_slide``). Errors surface as
    ``ValueError(detail)`` via ``_shared._check_response`` so the
    agent loop sees actionable messages.

  * **FastAPI router** — proxies HTTP requests from the *frontend* to
    the db-service with the user's bearer token forwarded verbatim.
    Each domain file owns its sub-router; ``router.py`` at this level
    assembles them under one parent.

Both surfaces of the same domain live in the same file. ``slides.py``
holds both ``slides.list_slides`` (typed client) and the ``@router.get
("/projects/{project_id}/slides")`` proxy handler, separated by a
section header. The router uses helpers from ``_shared_proxy.py``; the
client uses helpers from ``_shared.py``. Imports are tight per file.

Asymmetry by design:

  * ``auth.py`` — client only (no FE proxy)
  * ``admin.py`` — router only (admin endpoints are FE-only)
  * Everything else has both surfaces.
"""
