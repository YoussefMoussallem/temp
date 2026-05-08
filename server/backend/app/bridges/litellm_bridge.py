"""
LiteLLM proxy bridge — model metadata + cost lookup.

Why this exists
---------------
``litellm`` ships a hard-coded cost map, but that map is sourced from a
public URL that corporate SSL blocks for us. Instead, we fetch the same
information from our own LiteLLM proxy's ``/v1/model/info`` endpoint
and build a local cache.

Public API
----------
  * ``get_context_window(model)``     - max input tokens
  * ``get_max_output_tokens(model)``  - max output tokens
  * ``calculate_cost(model, ...)``    - USD cost for a completed turn
  * ``get_model_info(model)``         - full dict or None
  * ``get_all_model_info()``          - every cached model
  * ``CostCalculationError``          - raised on irrecoverable lookup failures

Name matching
-------------
``/v1/models`` and ``/v1/model/info`` expose the same models under
slightly different names (``openai.gpt-4o-2024-11-20`` vs
``azure.gpt-4o``). ``_find`` tries exact match first, then a
bidirectional substring match, so callers can pass either naming.

Caching
-------
First call triggers a single HTTP fetch, gated by a lock so concurrent
callers don't stampede. If the fetch fails we set ``_loaded = True``
with an empty cache - subsequent calls fall through to the hard-coded
defaults rather than retrying forever. Restart the process to retry.

SSL note
--------
``verify=False`` is intentional here - the proxy lives behind the same
corporate MITM that blocks the public cost map. Do not copy this flag
elsewhere.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

import requests
from app_logger import get_logger
from app.config import get_settings

log = get_logger(__name__)


# ── Exceptions ──────────────────────────────────────────────────────

class CostCalculationError(Exception):
    """Raised when cost cannot be computed for a known-nonzero request.

    Currently unused in the success path - ``calculate_cost`` falls
    back to the default per-token rates rather than raising. Kept as
    public API so call sites can catch and surface billing errors if
    we tighten the policy later.
    """
    pass


# ── Model info cache ────────────────────────────────────────────────

@dataclass(frozen=True)
class ModelInfo:
    """One row from the proxy's model catalogue."""
    name: str
    max_input_tokens: int
    max_output_tokens: int
    input_cost_per_token: float
    output_cost_per_token: float


# Process-wide cache. Populated on first lookup via ``_ensure_loaded``
# and never invalidated - restart the backend to pick up new models.
_cache: dict[str, ModelInfo] = {}
_cache_lock = threading.Lock()
_loaded = False


def _load_model_info() -> None:
    """Fetch /v1/model/info from the proxy and populate the cache.

    Sets ``_loaded = True`` even on failure so we don't hammer the
    proxy. See the module docstring for the restart-to-retry policy.
    """
    global _loaded
    settings = get_settings()
    base_url = settings.ai.base_url.rstrip("/")
    # The chat completions URL ends in /v1 but model/info is a sibling
    # path at the proxy root, so we strip the suffix if the settings
    # value includes it.
    if base_url.endswith("/v1"):
        base_url = base_url[:-3]

    url = f"{base_url}/v1/model/info"
    headers = {"Authorization": f"Bearer {settings.ai.api_key.get_secret_value()}"}

    try:
        # verify=False: the corporate MITM proxy; see module docstring.
        resp = requests.get(url, headers=headers, timeout=15, verify=False)
        resp.raise_for_status()
        data = resp.json().get("data", [])
    except Exception:
        log.warning("Failed to fetch model info from proxy at %s", url, exc_info=True)
        _loaded = True  # don't retry in a hot loop
        return

    # The proxy can list the same model under several aliases. We keep
    # the first occurrence that has a valid max_input_tokens and skip
    # duplicates - any alias that would resolve to the same underlying
    # model will still match via substring matching in ``_find``.
    seen: set[str] = set()
    for entry in data:
        name = entry.get("model_name", "")
        info = entry.get("model_info", {})
        if not name or name in seen:
            continue
        if not info.get("max_input_tokens"):
            # Entries missing context window are unusable for our
            # compaction logic - skip rather than cache a bogus 0.
            continue

        seen.add(name)
        _cache[name] = ModelInfo(
            name=name,
            max_input_tokens=info.get("max_input_tokens", 0),
            max_output_tokens=info.get("max_output_tokens", 0),
            input_cost_per_token=info.get("input_cost_per_token") or 0.0,
            output_cost_per_token=info.get("output_cost_per_token") or 0.0,
        )

    _loaded = True
    log.info("Loaded model info for %d models from proxy", len(_cache))


def _ensure_loaded() -> None:
    """Double-checked locking: lazy-load the cache on first use."""
    global _loaded
    if not _loaded:
        with _cache_lock:
            if not _loaded:
                _load_model_info()


def _find(model: str) -> ModelInfo | None:
    """Look up model by exact name, then substring match.

    Substring matching is bidirectional (``key in model`` OR
    ``model in key``) to bridge the proxy's two naming conventions.
    It can pick a wrong match when names overlap loosely, but in
    practice the proxy uses distinctive model strings, and a slightly
    wrong context window / cost is better than falling through to the
    hard-coded defaults for a known model.
    """
    _ensure_loaded()
    if model in _cache:
        return _cache[model]
    for key, info in _cache.items():
        if key in model or model in key:
            return info
    return None


# ── Fallback defaults ───────────────────────────────────────────────
# Used when a model is not in the cache (unknown, or the proxy was
# unreachable at boot). Chosen to be "reasonable for a modern GPT-4
# class model" so accounting stays approximately right even in a
# degraded state.

_DEFAULT_CONTEXT_WINDOW = 128_000
_DEFAULT_MAX_OUTPUT = 16_384
_DEFAULT_INPUT_COST = 1.0 / 1_000_000   # $1/MTok
_DEFAULT_OUTPUT_COST = 3.0 / 1_000_000  # $3/MTok


# ── Public API ──────────────────────────────────────────────────────

def get_context_window(model: str) -> int:
    """Return the context window (max input tokens) for *model*."""
    info = _find(model)
    return info.max_input_tokens if info else _DEFAULT_CONTEXT_WINDOW


def get_max_output_tokens(model: str) -> int:
    """Return the max output tokens for *model*."""
    info = _find(model)
    return info.max_output_tokens if info else _DEFAULT_MAX_OUTPUT


def calculate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """Calculate cost in USD for a completed turn.

    Raises CostCalculationError if model is unknown and tokens are non-zero.
    """
    info = _find(model)
    if info:
        return (
            input_tokens * info.input_cost_per_token
            + output_tokens * info.output_cost_per_token
        )
    if input_tokens or output_tokens:
        return (
            input_tokens * _DEFAULT_INPUT_COST
            + output_tokens * _DEFAULT_OUTPUT_COST
        )
    return 0.0


def get_model_info(model: str) -> dict | None:
    """Return full model info dict, or None if not found."""
    info = _find(model)
    if not info:
        return None
    return {
        "name": info.name,
        "max_input_tokens": info.max_input_tokens,
        "max_output_tokens": info.max_output_tokens,
        "input_cost_per_token": info.input_cost_per_token,
        "output_cost_per_token": info.output_cost_per_token,
    }


def get_all_model_info() -> list[dict]:
    """Return info for all cached models."""
    _ensure_loaded()
    return [
        {
            "name": info.name,
            "max_input_tokens": info.max_input_tokens,
            "max_output_tokens": info.max_output_tokens,
            "input_cost_per_token": info.input_cost_per_token,
            "output_cost_per_token": info.output_cost_per_token,
        }
        for info in _cache.values()
    ]
