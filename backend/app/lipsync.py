"""Адаптер lip sync (WP-M8): интерфейс без движка.

Условия запуска реального движка не выполнены: MLX-совместимая модель не выбрана,
лицензии весов и голоса не проверены, согласия на использование голоса нет, память
на 18 ГиБ не измерена. Поэтому движок не подключён, а любая попытка запуска
отклоняется явной ошибкой `lipsync_engine_not_selected`.

Legacy-заглушки `pipeline/stages/lipsync.py` и `pipeline/stages/voices.py`
(Hedra/ElevenLabs) не затрагиваются: это отдельный старый episode-пайплайн.
Никаких весов, TTS, внешних сервисов и новых зависимостей здесь нет.
"""

from __future__ import annotations

from dataclasses import dataclass

ENGINE_NOT_SELECTED = "lipsync_engine_not_selected"
ENGINE_NOT_IMPLEMENTED = "lipsync_engine_not_implemented"
REASON = (
    "движок lip sync не выбран: нет MLX-совместимой модели"
    " с проверенной лицензией весов и голоса"
)


@dataclass(frozen=True)
class LipsyncEngine:
    """Описание движка: имя, подпись и лицензионный статус весов."""

    name: str
    label: str
    license: str


# Реальный движок не выбран человеком — сюда попадает только проверенный MLX-движок.
SELECTED_ENGINE: LipsyncEngine | None = None


class LipsyncUnavailable(RuntimeError):
    """Запрошенный движок lip sync не выбран или объявлен, но не реализован."""

    def __init__(self, code: str = ENGINE_NOT_SELECTED, message: str = REASON) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def request_lip_sync() -> None:
    """Точка входа адаптера; пока движок не выбран — всегда исключение."""

    engine = SELECTED_ENGINE
    if engine is None:
        raise LipsyncUnavailable()
    raise LipsyncUnavailable(
        ENGINE_NOT_IMPLEMENTED, f"движок {engine.name} объявлен, но не реализован"
    )
