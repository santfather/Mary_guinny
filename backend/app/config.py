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
    # WP-05A: загрузка референсов (тот же BlobStore, что и у остальных ассетов).
    reference_upload_max_bytes: int = 32 * 1024 * 1024
    reference_max_pixels: int = 64 * 1024 * 1024
    # WP-05A: планировщик сцены. Vision — только советующий источник.
    ollama_base_url: str = "http://127.0.0.1:11434"
    planner_model: str = "gemma3:4b"
    planner_timeout_s: float = 120.0
    planner_max_images: int = 3
    planner_image_max_side: int = 768
    # WP-06: worker API. Токен обязателен (D7); пустое значение отключает API.
    worker_token: str = "change-me"
    worker_lease_seconds: int = 60
    worker_retry_backoff_s: int = 5
    worker_max_artifact_bytes: int = 256 * 1024 * 1024
