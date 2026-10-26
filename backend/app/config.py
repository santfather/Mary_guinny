from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки backend. Значения читаются только из переменных окружения."""

    model_config = SettingsConfigDict(env_prefix="MARY_", extra="ignore")

    database_url: str = "postgresql+psycopg://localhost:5432/mary_studio"
