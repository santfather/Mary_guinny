"""Адаптер Rhubarb Lip Sync 1.14.0 (WP-VOICE-06, §5 задания).

Роль: **опциональный источник viseme timing** для русского аудио
(`--recognizer phonetic` → JSON). Бинарник не скачивается: адаптер только
проверяет уже установленный файл (архитектура, SHA-256, лицензия) и разбирает
его JSON. Пока SHA-256 релиза не запинен человеком, статус — «не проверен», и
автотайминг через Rhubarb не используется.

Лицензия Rhubarb: MIT (`LICENSE.md` репозитория). Бинарник — CPU-only, отдельных
весов моделей нет. Официальная сборка macOS — `x86_64` (arm64-релиза у проекта нет),
поэтому на Apple Silicon она принимается только при доступной Rosetta 2: это
отражается в статусе (`rosetta`, `notes`), проверка SHA-256 остаётся обязательной.
Рядом с бинарником обязателен каталог `res/` — без него phonetic-распознавание
не работает.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

VERSION = "1.14.0"
LICENSE = "MIT"
RELEASE_PAGE = "https://github.com/DanielSWolf/rhubarb-lip-sync/releases/tag/v1.14.0"
EXPECTED_ARCH = "arm64"
ROSETTA_ARCH = "x86_64"
DEFAULT_BINARY = Path.home() / ".mary-studio" / "tools" / f"rhubarb-{VERSION}" / "rhubarb"

# A/B/C/D/E/F/G/H/X → пять форм рта набора. Соответствие по документации
# Rhubarb; на живом русском прогоне помечено [ПРОВЕРИТЬ].
SHAPE_TO_STATE = {
    "A": "closed",  # M, B, P — губы сомкнуты
    "B": "small_open",  # K, S, T, EE
    "C": "medium_open",  # EH, AE
    "D": "wide_open",  # AA
    "E": "rounded",  # AO, ER
    "F": "rounded",  # UW, OW, W
    "G": "small_open",  # F, V
    "H": "medium_open",  # L
    "X": "closed",  # покой / пауза
}
VISEME_STATES = ("closed", "small_open", "medium_open", "wide_open", "rounded")
SUPPORTED_SUFFIXES = (".wav", ".ogg")


class RhubarbError(ValueError):
    """Ошибка с машинным кодом для API."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class RhubarbStatus:
    installed: bool
    verified: bool
    path: str
    version: str = VERSION
    license: str = LICENSE
    release_page: str = RELEASE_PAGE
    arch: str | None = None
    sha256: str | None = None
    rosetta: bool | None = None
    reasons: list[dict[str, str]] = field(default_factory=list)
    notes: list[dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "installed": self.installed,
            "verified": self.verified,
            "path": self.path,
            "version": self.version,
            "license": self.license,
            "release_page": self.release_page,
            "arch": self.arch,
            "sha256": self.sha256,
            "rosetta": self.rosetta,
            "reasons": list(self.reasons),
            "notes": list(self.notes),
            "expected_arch": EXPECTED_ARCH,
            "download_performed": False,
        }


def binary_path(configured: Path | None = None) -> Path:
    return Path(configured) if configured is not None else DEFAULT_BINARY


def file_architecture(path: Path) -> str:
    """Архитектура Mach-O через `file -b`; при отсутствии `file` — пустая строка."""

    try:
        result = subprocess.run(
            ["file", "-b", str(path)],
            capture_output=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.decode("utf-8", errors="replace").strip()


def rosetta_available() -> bool:
    """Rosetta 2 доступна: x86_64-процесс запускается через `arch -x86_64`."""

    if platform.system() != "Darwin" or platform.machine() != "arm64":
        return False
    try:
        result = subprocess.run(
            ["arch", "-x86_64", "/usr/bin/true"],
            capture_output=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_binary(
    *,
    configured: Path | None = None,
    expected_sha256: str = "",
) -> RhubarbStatus:
    """Проверяет установленный бинарник. Ничего не скачивает и не запускает."""

    path = binary_path(configured)
    status = RhubarbStatus(
        installed=path.is_file(),
        verified=False,
        path=str(path),
    )
    if not status.installed:
        status.reasons.append(
            {
                "code": "rhubarb_not_installed",
                "message": (
                    f"Rhubarb {VERSION} не установлен в {path}. Скачивание — только "
                    "с разрешения человека."
                ),
            }
        )
        return status

    if not path.stat().st_mode & 0o111:
        status.reasons.append(
            {"code": "rhubarb_not_executable", "message": "файл не исполняемый"}
        )

    res_dir = path.parent / "res"
    if not res_dir.is_dir():
        status.reasons.append(
            {
                "code": "rhubarb_res_missing",
                "message": f"рядом с бинарником нет каталога res/: {res_dir}",
            }
        )

    arch = file_architecture(path)
    status.arch = arch
    if platform.system() == "Darwin":
        if "arm64" in arch:
            pass
        elif arch == "":
            status.reasons.append(
                {
                    "code": "rhubarb_arch_unknown",
                    "message": "не удалось определить архитектуру бинарника",
                }
            )
        elif ROSETTA_ARCH in arch:
            # Официальная сборка macOS — x86_64; arm64-релиза у проекта нет.
            status.rosetta = rosetta_available()
            if status.rosetta:
                status.notes.append(
                    {
                        "code": "rhubarb_runs_under_rosetta",
                        "message": (
                            "сборка x86_64 исполняется через Rosetta 2; "
                            "это медленнее нативной arm64"
                        ),
                    }
                )
            else:
                status.reasons.append(
                    {
                        "code": "rhubarb_arch_unsupported",
                        "message": f"бинарник x86_64, Rosetta 2 недоступна: {arch}",
                    }
                )
        else:
            status.reasons.append(
                {
                    "code": "rhubarb_arch_unsupported",
                    "message": f"бинарник не arm64/x86_64: {arch}",
                }
            )

    status.sha256 = sha256_of(path)
    pinned = expected_sha256.strip().lower()
    if not pinned:
        status.reasons.append(
            {
                "code": "rhubarb_sha256_not_pinned",
                "message": (
                    "SHA-256 релиза не запинен: укажите MARY_RHUBARB_SHA256 после "
                    "ручной проверки скачанного архива"
                ),
            }
        )
    elif status.sha256 != pinned:
        status.reasons.append(
            {
                "code": "rhubarb_sha256_mismatch",
                "message": "SHA-256 бинарника не совпал с закреплённым значением",
            }
        )

    status.verified = not status.reasons
    return status


def require_verified(
    *, configured: Path | None = None, expected_sha256: str = ""
) -> RhubarbStatus:
    status = verify_binary(configured=configured, expected_sha256=expected_sha256)
    if not status.verified:
        reason = status.reasons[0]
        raise RhubarbError(reason["code"], reason["message"])
    return status


def parse_output(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Rhubarb JSON (`mouthCues`) → тайминги движка `viseme_frame_blend_v1`."""

    cues = payload.get("mouthCues")
    if not isinstance(cues, list) or not cues:
        raise RhubarbError("rhubarb_output_invalid", "в JSON нет mouthCues")
    spans: list[dict[str, Any]] = []
    for index, cue in enumerate(cues):
        if not isinstance(cue, dict):
            raise RhubarbError("rhubarb_output_invalid", f"элемент {index} не объект")
        start = cue.get("start")
        end = cue.get("end")
        shape = cue.get("value")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            raise RhubarbError("rhubarb_output_invalid", f"элемент {index}: нет start/end")
        if not isinstance(shape, str):
            raise RhubarbError("rhubarb_output_invalid", f"элемент {index}: нет value")
        mapped = shape if shape in VISEME_STATES else SHAPE_TO_STATE.get(shape.upper())
        if mapped is None:
            raise RhubarbError("rhubarb_output_invalid", f"неизвестная форма {shape}")
        spans.append(
            {"start": round(float(start), 4), "end": round(float(end), 4), "viseme": mapped}
        )
    return spans


def check_pauses(
    spans: list[dict[str, Any]],
    silence_segments: list[dict[str, Any]],
    *,
    tolerance_s: float = 0.15,
) -> list[dict[str, Any]]:
    """Сверяет виземные паузы с паузами записи.

    Возвращает предупреждения, а не ошибки: Rhubarb может держать рот закрытым
    раньше/позже огибающей.
    """

    warnings: list[dict[str, Any]] = []
    for segment in silence_segments:
        start = segment.get("start_s")
        end = segment.get("end_s")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            continue
        if (end - start) < 0.12:
            continue
        covered = 0.0
        for span in spans:
            if span.get("viseme") != "closed":
                continue
            overlap = min(end, span["end"]) - max(start, span["start"])
            if overlap > 0:
                covered += overlap
        if (end - start) - covered > tolerance_s:
            warnings.append(
                {
                    "code": "viseme_pause_not_closed",
                    "message": (
                        f"пауза {start:.2f}–{end:.2f} с закрыта лишь на {covered:.2f} с"
                    ),
                }
            )
    return warnings


def analyze(
    audio_path: Path,
    *,
    configured: Path | None = None,
    expected_sha256: str = "",
    recognizer: str = "phonetic",
    timeout_s: float = 300.0,
) -> list[dict[str, Any]]:
    """Запускает установленный Rhubarb и возвращает тайминги виземов.

    Требует проверенного бинарника (архитектура + закреплённый SHA-256).
    """

    status = require_verified(configured=configured, expected_sha256=expected_sha256)
    if audio_path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise RhubarbError(
            "rhubarb_input_unsupported",
            f"Rhubarb принимает только .wav/.ogg, получено «{audio_path.suffix}»",
        )
    binary = Path(status.path)
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "rhubarb.json"
        command = [
            str(binary),
            "-r",
            recognizer,
            "-f",
            "json",
            "-o",
            str(output_path),
            str(audio_path),
        ]
        try:
            result = subprocess.run(
                command, capture_output=True, check=False, timeout=timeout_s
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise RhubarbError("rhubarb_failed", str(error)) from error
        if result.returncode != 0:
            raise RhubarbError(
                "rhubarb_failed",
                result.stderr.decode("utf-8", errors="replace")
                or f"exit {result.returncode}",
            )
        try:
            payload = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise RhubarbError("rhubarb_output_invalid", str(error)) from error
    return parse_output(payload)
