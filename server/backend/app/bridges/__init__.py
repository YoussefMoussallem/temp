"""Bridge modules — adapters between external services and the app.

A "bridge" in this codebase is a thin translation layer that:

  * Takes app-level configuration (from ``app.config``) and feeds it to
    a third-party library or remote service.
  * Exposes a small, stable function surface to the rest of the app so
    callers never import the vendor SDK directly.

Keeping these imports isolated here means swapping vendors (e.g.
Langfuse -> something else, or httpx -> aiohttp) touches exactly one
file. Bridges should contain no business logic - just configuration
plumbing and lightweight request/response shaping.

Current bridges:
  * ``db_client``       - HTTP client for the db-service microservice.
  * ``langfuse_bridge`` - Langfuse tracing init + hook registration.
  * ``litellm_bridge``  - Model metadata + cost lookup via LiteLLM proxy.
  * ``logging_bridge``  - Feeds app settings into ``app_logger``.
  * ``provider_bridge`` - LLM adapter factory (cached).
"""
