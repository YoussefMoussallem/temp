"""Application configuration — grouped, thread-safe singleton.

Two layers on purpose:

1. ``_EnvSettings`` is a flat pydantic-settings model whose field names
   match env var keys (and, in dev, the keys in ``backend/.env``). This
   is the only place that reads env vars / .env files and the only
   place secrets exist as plain strings.

2. ``Settings`` reshapes that flat object into typed, frozen
   sub-settings grouped by concern (``settings.ai.api_key``,
   ``settings.logging.level``, etc.). Credentials are wrapped in
   ``SecretStr`` so accidental ``repr`` / ``log`` of a sub-settings
   object redacts them; call ``.get_secret_value()`` at the site of
   use only.

Frozen sub-models prevent code from mutating settings at runtime, and
the singleton is built with double-checked locking so the first caller
wins on startup regardless of thread.

Environment-aware behaviour
---------------------------
``EDWIN_ENVIRONMENT`` is the master switch:

* ``production``: ``.env`` files are NEVER loaded — every key must
  arrive as a real environment variable (Docker/K8s env, Azure App
  Service config, etc.). Production also enforces non-empty values
  for credentials (see ``_validate_production``).
* ``staging`` / ``development``: ``.env`` is loaded if present at
  ``backend/.env`` (override path with ``EDWIN_ENV_FILE``).

In every environment, every field on ``_EnvSettings`` is required —
no defaults. A missing key crashes the process at boot with a clear
"Field required" error rather than silently falling back. This makes
config drift / typos in env keys immediately visible.

The env-file path is resolved at module import time. In a production
container ``EDWIN_ENVIRONMENT=production`` must be set as a real env
var before Python starts; setting it inside a ``.env`` is treated as
"this is dev" because the file would never be read in prod anyway.

To add a new setting:
  1. Add a field to ``_EnvSettings`` (matching the env key, no default).
  2. Add it to the relevant frozen sub-settings model.
  3. Wire it through ``Settings.__init__`` from env -> sub-settings.
  4. Add the corresponding entry to ``backend/.env`` and
     ``backend/.env.example``.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_BACKEND_DIR = Path(__file__).resolve().parent.parent

Environment = Literal["development", "staging", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
ReasoningEffort = Literal["low", "medium", "high"]


def _resolve_env_file() -> str | None:
    """Decide which (if any) .env file to feed pydantic-settings.

    Production deliberately ignores .env files entirely — secrets
    arrive as real environment variables. This avoids accidentally
    shipping a stale .env into a container image.

    Non-production loads ``$EDWIN_ENV_FILE`` if set, else
    ``backend/.env`` if it exists, else nothing. Missing files are
    silently skipped (CI / smoke runs).
    """
    env = os.getenv("EDWIN_ENVIRONMENT", "development").lower()
    if env == "production":
        return None
    explicit = os.getenv("EDWIN_ENV_FILE")
    if explicit:
        return explicit
    default = _BACKEND_DIR / ".env"
    return str(default) if default.is_file() else None


class AppSettings(BaseModel, frozen=True):
    """Top-level app identity and infrastructure dependencies."""

    name: str
    db_service_url: str


class AzureADSettings(BaseModel, frozen=True):
    """Azure AD app registration IDs used for auth / admin endpoints."""

    client_id: str
    tenant_id: str
    admin_client_id: str


class AISettings(BaseModel, frozen=True):
    """LLM provider config (OpenAI-compatible endpoint)."""

    api_key: SecretStr
    base_url: str
    default_model: str
    search_model: str = ""  # optional - falls back to mainLoopModel when blank
    stream_timeout: int = Field(gt=0)
    reasoning_effort: ReasoningEffort


class ObservabilitySettings(BaseModel, frozen=True):
    """Langfuse tracing. Disabled by default; secrets are optional in dev."""

    langfuse_enabled: bool
    langfuse_base_url: str
    langfuse_public_key: str
    langfuse_secret_key: SecretStr
    langfuse_proxy_token: SecretStr = SecretStr("")
    langfuse_cacert_path: str


class LoggingSettings(BaseModel, frozen=True):
    """Local + Azure Blob log sink config.

    When ``azure_enabled`` is true, logs batch up to ``azure_batch_size``
    entries or flush every ``azure_flush_interval_seconds``, whichever
    comes first.
    """

    level: LogLevel
    local_enabled: bool
    log_dir: str
    azure_enabled: bool
    azure_connection_string: SecretStr
    azure_container_name: str
    azure_blob_prefix: str
    azure_batch_size: int = Field(gt=0)
    azure_flush_interval_seconds: int = Field(gt=0)


class CompactionSettings(BaseModel, frozen=True):
    """Conversation compaction thresholds for the agent loop.

    Edwin-specific Phase-3 thresholds (``autocompact_threshold_tokens``
    and ``warning_threshold_tokens``) are env-overridable so the
    pipeline can be exercised at small context sizes during testing
    without recompiling. ``0`` means "use the code default" (160K
    autocompact, 70% of that for the warning).
    """

    auto_trigger_ratio: float = Field(ge=0.0, le=1.0)
    collapse_trigger_low: float = Field(ge=0.0, le=1.0)
    collapse_trigger_high: float = Field(ge=0.0, le=1.0)
    preserve_recent: int = Field(ge=0)
    emergency_preserve_recent: int = Field(ge=0)
    micro_keep_last: int = Field(ge=0)
    autocompact_threshold_tokens: int = Field(default=0, ge=0)
    warning_threshold_tokens: int = Field(default=0, ge=0)


# ── Env-file loader (flat keys match env names) ──────────────────────
# Every field is REQUIRED — missing keys fail at boot. This is
# deliberate: it makes config drift and env-key typos visible
# immediately rather than silently falling back to a default.
#
# Empty values are still allowed at parse time (``KEY=`` parses as ``""``
# for ``str`` fields) — ``_validate_production`` catches blank
# credentials in production.
#
# ``extra="ignore"`` is intentional: the .env in dev may hold keys for
# sibling services (db-service, etc.). Typos in *known* keys still fail
# loudly because the matching field has no default to fall back to.


class _EnvSettings(BaseSettings):
    """Flat view of every configurable value, sourced from env (+ .env in dev).

    Field names map case-insensitively to env var names. Every field
    is required — see module docstring for rationale.
    """

    model_config = SettingsConfigDict(
        env_file=_resolve_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App settings
    app_name: str
    edwin_environment: Environment
    db_service_url: str

    # Azure AD
    azure_client_id: str
    azure_tenant_id: str
    azure_admin_client_id: str

    # AI Settings
    llm_api_key: str
    llm_base_url: str
    stream_timeout_seconds: int
    search_llm_model: str
    default_llm_model: str
    reasoning_effort: ReasoningEffort

    # Observability settings - Langfuse
    langfuse_public_key: str
    langfuse_secret_key: str
    langfuse_proxy_token: str
    langfuse_cacert_path: str
    langfuse_enabled: bool
    langfuse_base_url: str

    # Log settings
    log_level: LogLevel
    log_local_enabled: bool
    log_dir: str
    log_azure_enabled: bool
    log_azure_connection_string: str
    log_azure_container: str
    log_azure_blob_prefix: str
    log_azure_batch_size: int
    log_azure_flush_interval: int

    # Compaction
    compaction_auto_trigger_ratio: float
    compaction_collapse_trigger_low: float
    compaction_collapse_trigger_high: float
    compaction_preserve_recent: int
    compaction_emergency_preserve_recent: int
    compaction_micro_keep_last: int
    # Phase-3 overrides. ``0`` = use the constant baked into
    # ``services/compact/auto_compact.py`` and
    # ``services/compact/compact_warning_state.py``. Anything > 0
    # replaces the default at module-load time.
    edwin_autocompact_threshold_tokens: int
    edwin_warning_threshold_tokens: int

    @model_validator(mode="after")
    def _validate_invariants(self) -> _EnvSettings:
        """Cross-field checks that must hold regardless of environment.

        Production gets a stricter pass via ``_validate_production``.
        """
        if self.langfuse_enabled and not (self.langfuse_secret_key and self.langfuse_public_key):
            raise ValueError(
                "langfuse_enabled=True requires LANGFUSE_SECRET_KEY and "
                "LANGFUSE_PUBLIC_KEY to be set."
            )
        if self.log_azure_enabled and not self.log_azure_connection_string:
            raise ValueError("log_azure_enabled=True requires LOG_AZURE_CONNECTION_STRING.")
        if self.compaction_collapse_trigger_high < self.compaction_collapse_trigger_low:
            raise ValueError(
                "compaction_collapse_trigger_high must be >= compaction_collapse_trigger_low."
            )
        if self.edwin_environment == "production":
            self._validate_production()
        return self

    def _validate_production(self) -> None:
        """Refuse to boot in production without required secrets/config.

        Catches the "deployment forgot to set a secret" failure mode at
        startup instead of on the first request that touches the value.
        """
        missing: list[str] = []
        if not self.llm_api_key:
            missing.append("LLM_API_KEY")
        if not self.llm_base_url:
            missing.append("LLM_BASE_URL")
        if not self.azure_client_id:
            missing.append("AZURE_CLIENT_ID")
        if not self.azure_tenant_id:
            missing.append("AZURE_TENANT_ID")
        if not self.azure_admin_client_id:
            missing.append("AZURE_ADMIN_CLIENT_ID")
        if self.db_service_url in ("", "http://localhost:8001"):
            missing.append("DB_SERVICE_URL (must be explicit, not the localhost default)")
        if missing:
            raise ValueError(
                "Production environment is missing required configuration: " + ", ".join(missing)
            )


# ── Thread-safe singleton ─────────────────────────────────────────────


class Settings:
    """Groups all configuration under typed, frozen sub-settings.

    Access via ``Settings.get()`` or the module-level ``get_settings()``.
    Uses double-checked locking so the singleton is safe across threads.

    Secrets on sub-settings are ``SecretStr`` — call
    ``.get_secret_value()`` at the site of use, never log the wrapping
    sub-settings object directly.

    Do not instantiate directly — go through ``get_settings()``. The
    ``__init__`` takes an ``_EnvSettings`` so tests can construct a
    ``Settings`` with a stub env without touching the real singleton.
    """

    _instance: Settings | None = None
    _lock: threading.Lock = threading.Lock()

    def __init__(self, env: _EnvSettings) -> None:
        self.app = AppSettings(
            name=env.app_name,
            db_service_url=env.db_service_url,
        )
        self.azure_ad = AzureADSettings(
            client_id=env.azure_client_id,
            tenant_id=env.azure_tenant_id,
            admin_client_id=env.azure_admin_client_id,
        )
        self.ai = AISettings(
            api_key=SecretStr(env.llm_api_key),
            base_url=env.llm_base_url,
            default_model=env.default_llm_model,
            search_model=env.search_llm_model,
            stream_timeout=env.stream_timeout_seconds,
            reasoning_effort=env.reasoning_effort,
        )
        self.observability = ObservabilitySettings(
            langfuse_public_key=env.langfuse_public_key,
            langfuse_secret_key=SecretStr(env.langfuse_secret_key),
            langfuse_base_url=env.langfuse_base_url,
            langfuse_enabled=env.langfuse_enabled,
            langfuse_proxy_token=SecretStr(env.langfuse_proxy_token),
            langfuse_cacert_path=env.langfuse_cacert_path,
        )
        self.logging = LoggingSettings(
            level=env.log_level,
            local_enabled=env.log_local_enabled,
            log_dir=env.log_dir,
            azure_enabled=env.log_azure_enabled,
            azure_connection_string=SecretStr(env.log_azure_connection_string),
            azure_container_name=env.log_azure_container,
            azure_blob_prefix=env.log_azure_blob_prefix,
            azure_batch_size=env.log_azure_batch_size,
            azure_flush_interval_seconds=env.log_azure_flush_interval,
        )
        self.compaction = CompactionSettings(
            auto_trigger_ratio=env.compaction_auto_trigger_ratio,
            collapse_trigger_low=env.compaction_collapse_trigger_low,
            collapse_trigger_high=env.compaction_collapse_trigger_high,
            preserve_recent=env.compaction_preserve_recent,
            emergency_preserve_recent=env.compaction_emergency_preserve_recent,
            micro_keep_last=env.compaction_micro_keep_last,
            autocompact_threshold_tokens=env.edwin_autocompact_threshold_tokens,
            warning_threshold_tokens=env.edwin_warning_threshold_tokens,
        )

    @classmethod
    def get(cls) -> Settings:
        """Return the process-wide Settings, building it on first access.

        Double-checked locking: the fast path skips the lock once the
        instance is built, so steady-state calls are lock-free.
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(_EnvSettings())
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Drop the cached singleton (useful in tests)."""
        with cls._lock:
            cls._instance = None


def get_settings() -> Settings:
    """Preferred accessor. Thin wrapper around ``Settings.get()``."""
    return Settings.get()


# Eager load at import time so a broken env fails fast on boot rather
# than on the first request that happens to touch config.
settings = get_settings()
