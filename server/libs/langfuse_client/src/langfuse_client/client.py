"""Langfuse client initialisation and accessor.

Wraps the Langfuse SDK's global-singleton pattern behind a tiny, service-
agnostic surface. Services call :func:`init_client` once at startup with
credentials pulled from config; every other module uses :func:`get_client`
(or the context helpers in :mod:`langfuse_client.tracing`) and never touches
the Langfuse SDK directly. Makes it easy to swap providers or stub tracing
out in tests.
"""

from __future__ import annotations

from langfuse import Langfuse
from langfuse import get_client as _get_client
import httpx

__all__ = ["init_client", "get_client"]


def init_client(
    public_key: str,
    secret_key: str,
    base_url: str = "https://cloud.langfuse.com",
    httpx_client: httpx.Client = None,
    additional_headers: dict | None = None,
) -> None:
    """Initialise the global Langfuse singleton.

    Constructing :class:`Langfuse` has the side effect of registering it as
    the process-wide client — :func:`langfuse.get_client` will return it
    afterwards. Call this once from the service's startup hook.

    Args:
        public_key: Langfuse project public key.
        secret_key: Langfuse project secret key.
        base_url: Langfuse instance URL. Override for self-hosted deployments
            or the EU cloud endpoint; defaults to Langfuse Cloud US.
        httpx_client: Custom httpx client used for the ingestion REST API.
        additional_headers: Extra HTTP headers attached to the OTLP trace
            exporter (which does not inherit ``httpx_client``'s headers).
            Needed for proxy/gateway auth on both the REST and OTLP paths.
    """
    Langfuse(
        public_key=public_key,
        secret_key=secret_key,
        base_url=base_url,
        httpx_client=httpx_client,
        additional_headers=additional_headers,
    )


def get_client():
    """Return the active Langfuse client, or ``None`` if uninitialised.

    Returning ``None`` (rather than raising) lets callers run with tracing
    disabled — useful in local dev, unit tests, or when credentials aren't
    configured. The tracing helpers rely on this behaviour.
    """
    return _get_client()
