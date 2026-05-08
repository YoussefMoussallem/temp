"""Langfuse initialization and hook-registration bridge.

Langfuse is our LLM tracing backend. It's optional - the backend runs
fine without it, which is why every call here is a no-op when
``observability.langfuse_enabled`` is false.

Why the imports are deferred
----------------------------
``langfuse_client`` and ``app.agent.hooks.langfuse_hooks`` pull in the
real Langfuse SDK, which is a heavy dependency we don't want to load
when tracing is disabled (slower boot, extra memory, and it would
fail loudly on machines without Langfuse installed). Importing them
inside the guarded function makes the cost pay-per-use.

Two-phase init
--------------
  1. ``init_langfuse()`` - boots the Langfuse client at process start
     (called from ``app.main``).
  2. ``register_langfuse_hooks_if_enabled(engine)`` - attaches the
     tool/lifecycle hooks to a specific agent ``HookEngine`` so each
     agent turn emits spans. Called during agent setup, not at boot,
     because the engine is per-turn.
"""

from __future__ import annotations
import httpx 
import httpx 
from app_logger import get_logger
from app.config import get_settings
import os 


logger = get_logger(__name__)

def init_langfuse() -> None:
    """Initialize the Langfuse client once, if enabled in settings.

    Failures are logged but never raised - a broken observability
    pipeline must not prevent the app from serving requests.
    """
    obs = get_settings().observability
    if not obs.langfuse_enabled:
        return
    from langfuse_client import init_client  # noqa: PLC0415  (deferred import - see module docstring)
    headers = {}
    proxy_token = obs.langfuse_proxy_token.get_secret_value()
    if proxy_token:
        headers["Proxy-Authorization"] = proxy_token
    httpx_client = httpx.Client(verify=obs.langfuse_cacert_path, headers=headers, timeout=5.0)
    
    try:
        init_client(
            public_key=obs.langfuse_public_key,
            secret_key=obs.langfuse_secret_key.get_secret_value(),
            base_url=obs.langfuse_base_url,
            httpx_client=httpx_client,
            additional_headers=headers or None,
        )
        logger.info("Langfuse tracing enabled (host=%s)", obs.langfuse_base_url)
    except Exception:
        logger.warning("Failed to initialise Langfuse client", exc_info=True)

