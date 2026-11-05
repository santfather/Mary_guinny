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
    # WP-M6: голосовой образец персонажа (reference_assets role='voice').
    voice_upload_max_bytes: int = 16 * 1024 * 1024
    voice_max_duration_s: float = 30.0
    # WP-VOICE-02: аудио шота (reference_assets role='shot_audio') и mouth-анимация.
    shot_audio_upload_max_bytes: int = 32 * 1024 * 1024
    shot_audio_max_duration_s: float = 120.0
    mouth_animation_fps: int = 24
    mouth_animation_max_side: int = 1080
    # WP-VOICE-06: набор viseme-кадров (reference_assets role='viseme_<state>').
    viseme_upload_max_bytes: int = 32 * 1024 * 1024
    viseme_blend_ms: float = 60.0
    viseme_min_hold_ms: float = 60.0
    viseme_outside_max_ratio: float = 0.01
    viseme_max_shift_px: int = 8
    # WP-VOICE-06: Rhubarb Lip Sync проверяется локально, скачивание не выполняется.
    rhubarb_binary: Path = Path.home() / ".mary-studio" / "tools" / "rhubarb-1.14.0" / "rhubarb"
    rhubarb_sha256: str = ""
    # WP-05A: планировщик сцены. Vision — только советующий источник.
    ollama_base_url: str = "http://127.0.0.1:11434"
    planner_model: str = "gemma3:4b"
    planner_timeout_s: float = 120.0
    planner_max_images: int = 3
    planner_image_max_side: int = 768
    # WP-M3: сколько раз переспрашивать модель при невалидном плане.
    planner_max_repair: int = 2
    # WP-06: worker API. Токен обязателен (D7); пустое значение отключает API.
    worker_token: str = "change-me"
    worker_lease_seconds: int = 60
    worker_retry_backoff_s: int = 5
    worker_max_artifact_bytes: int = 256 * 1024 * 1024
    # WP-THERMAL-02 (Q-29): read-only статус render-agent читает файлы воркера.
    render_agent_state_path: Path = Path.home() / ".mary-studio" / "thermal-state.json"
    render_agent_events_path: Path = Path.home() / ".mary-studio" / "thermal-events.jsonl"
    render_agent_stale_seconds: float = 180.0
