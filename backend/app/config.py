from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Настройки backend. Значения читаются только из переменных окружения."""

    model_config = SettingsConfigDict(env_prefix="MARY_", extra="ignore")

    database_url: str = "postgresql+psycopg://localhost:5432/mary_studio"
    # D3: storage — локальный каталог вне Git; в БД только относительные storage_key.
    storage_root: Path = REPO_ROOT / "storage"
    # Корень legacy-дерева (characters/, episodes/) для импорта (WP-03).
    legacy_root: Path = REPO_ROOT
    # D2: лимиты синхронного композитора PNG (WP-05).
    composition_max_pixels: int = 16 * 1024 * 1024
    composition_max_layers: int = 16
