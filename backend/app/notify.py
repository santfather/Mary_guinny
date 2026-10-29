"""macOS-уведомления о событиях прогона серии (WP-N4).

Best-effort: баннер не влияет на статус прогона. Отключается
`MARY_DISABLE_NOTIFY=1`, на не-macOS платформах молча не делает ничего.
"""

from __future__ import annotations

import os
import subprocess
import sys

_MAX_LENGTH = 180


def _literal(value: str) -> str:
    cleaned = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
    return f'"{cleaned[:_MAX_LENGTH]}"'


def notify(title: str, message: str) -> None:
    """Показывает баннер; любые ошибки osascript подавляются."""

    if os.environ.get("MARY_DISABLE_NOTIFY") == "1" or sys.platform != "darwin":
        return
    script = f"display notification {_literal(message)} with title {_literal(title)}"
    try:
        subprocess.run(
            ["osascript", "-e", script],
            check=False,
            capture_output=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return
