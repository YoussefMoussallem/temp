"""DB service configuration."""

from __future__ import annotations

import threading
from pathlib import Path

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

_SERVICE_DIR = Path(__file__).resolve().parent.parent


class AzureADSettings(BaseModel, frozen=True):
    client_id: str
    tenant_id: str
    admin_client_id: str


class _EnvSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_SERVICE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    azure_client_id: str = ""
    azure_tenant_id: str = ""
    azure_admin_client_id: str = ""


class Settings:
    _instance: Settings | None = None
    _lock: threading.Lock = threading.Lock()

    def __init__(self, env: _EnvSettings) -> None:
        self.azure_ad = AzureADSettings(
            client_id=env.azure_client_id,
            tenant_id=env.azure_tenant_id,
            admin_client_id=env.azure_admin_client_id,
        )

    @classmethod
    def get(cls) -> Settings:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(_EnvSettings())
        return cls._instance


def get_settings() -> Settings:
    return Settings.get()
