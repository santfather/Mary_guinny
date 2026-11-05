"""Thermal-safe планировщик воркера (WP-THERMAL-02).

Модуль отвечает только за допуск к следующему рендеру: тепловое состояние,
питание, давление на память, cooldown и журнал решений. Параметры рендера
(разрешение, кадры, cfg, seed) он не меняет — это границы Eco из Q-33.

Источники:
- thermal — Swift-helper `scripts/mac_thermal_state.swift` (`ProcessInfo.thermalState`);
  вывод `{"state": "nominal|fair|serious|critical", "source": "process_info"}`;
  отсутствие helper'а, таймаут или мусор в выводе → `unknown`;
- power — `pmset -g ps`;
- memory — `sysctl -n kern.memorystatus_vm_pressure_level` и `vm_stat`.

Состояние — `~/.mary-studio/thermal-state.json` (атомарная запись), журнал —
`~/.mary-studio/thermal-events.jsonl` с ротацией. Новых записей в БД нет.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

GIB = 1024**3
PROFILE_NAMES = ("off", "balanced", "eco")
THERMAL_STATES = ("nominal", "fair", "serious", "critical", "unknown")
THERMAL_PAUSE_REASONS = ("thermal_serious", "thermal_critical")
MIN_BATTERY_PERCENT = 50.0

DEFAULT_STATE_FILE = Path.home() / ".mary-studio" / "thermal-state.json"
DEFAULT_LOG_FILE = Path.home() / ".mary-studio" / "thermal-events.jsonl"
DEFAULT_HELPER = Path.home() / ".mary-studio" / "bin" / "mary-thermal-state"
HELPER_SOURCE = Path(__file__).resolve().parent.parent / "scripts" / "mac_thermal_state.swift"

PAGE_COUNTERS = ("Pages free", "Pages inactive", "Pages speculative")
PRESSURE_NAMES = {1: "normal", 2: "warning", 4: "critical"}

CommandRunner = Callable[[list[str]], "str | None"]


@dataclass(frozen=True)
class ThermalReading:
    state: str = "unknown"
    source: str = "none"


@dataclass(frozen=True)
class PowerReading:
    source: str = "unknown"
    battery_percent: float | None = None


@dataclass(frozen=True)
class MemoryReading:
    pressure: str = "unknown"
    pressure_level: int | None = None
    available_bytes: int | None = None


@dataclass(frozen=True)
class Profile:
    """Политика допуска. Параметры рендера здесь отсутствуют намеренно (Q-33)."""

    name: str
    require_ac: bool = False
    min_free_gib: float = 0.0
    require_normal_pressure: bool = False
    cooldown_between_s: float = 0.0
    cooldown_after_batch_s: float = 0.0
    batch_size: int = 3
    unknown_thermal_floor_s: float = 0.0
    recovery_required: bool = True
    recovery_samples: int = 2
    recovery_cooldown_s: float = 600.0


PROFILES: dict[str, Profile] = {
    # off — прежнее поведение: допуск без проверок (ручной запуск человеком).
    "off": Profile(name="off", cooldown_between_s=0.0, cooldown_after_batch_s=0.0),
    # balanced — умолчание: паузы как у Eco, но без требований к питанию/памяти.
    "balanced": Profile(
        name="balanced",
        min_free_gib=2.0,
        cooldown_between_s=480.0,
        cooldown_after_batch_s=1200.0,
        unknown_thermal_floor_s=900.0,
    ),
    # eco — Q-30: сеть, normal memory pressure, 4 ГиБ запаса, паузы между шотами.
    "eco": Profile(
        name="eco",
        require_ac=True,
        min_free_gib=4.0,
        require_normal_pressure=True,
        cooldown_between_s=480.0,
        cooldown_after_batch_s=1200.0,
        batch_size=3,
        unknown_thermal_floor_s=900.0,
    ),
}


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str | None
    wait_seconds: float = 0.0
    thermal: ThermalReading = ThermalReading()
    power: PowerReading = PowerReading()
    memory: MemoryReading = MemoryReading()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def parse_iso(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def run_command(command: list[str], timeout: float = 3.0) -> str | None:
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout


def parse_thermal(text: str | None, source: str = "process_info") -> ThermalReading:
    """JSON helper'а → состояние. Пустой вывод не считается `nominal`."""

    if not text or not text.strip():
        return ThermalReading("unknown", "none")
    line = text.strip().splitlines()[-1]
    try:
        payload = json.loads(line)
    except ValueError:
        return ThermalReading("unknown", "invalid")
    if not isinstance(payload, dict):
        return ThermalReading("unknown", "invalid")
    state = str(payload.get("state") or "").strip().lower()
    if state not in THERMAL_STATES:
        return ThermalReading("unknown", source)
    origin = str(payload.get("source") or source)
    return ThermalReading(state, origin)


def parse_power(text: str | None) -> PowerReading:
    if not text:
        return PowerReading()
    lower = text.lower()
    if "ac power" in lower:
        source = "ac"
    elif "battery power" in lower:
        source = "battery"
    else:
        source = "unknown"
    percent: float | None = None
    for token in text.replace(";", " ").split():
        if token.endswith("%"):
            try:
                percent = float(token.rstrip("%"))
            except ValueError:
                percent = None
            break
    return PowerReading(source, percent)


def parse_low_power_mode(text: str | None) -> bool | None:
    """Low Power Mode из `pmset -g` (только чтение, WP-THERMAL-03/T-06).

    `None` — источник недоступен или поле отсутствует: UI обязан показать Unknown,
    а не выдумывать выключенный режим.
    """

    if not text:
        return None
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] == "lowpowermode":
            if parts[1] in ("0", "1"):
                return parts[1] == "1"
            return None
    return None


def parse_pressure_level(text: str | None) -> int | None:
    if not text or not text.strip().isdigit():
        return None
    return int(text.strip())


def parse_vm_stat(text: str | None) -> int | None:
    """Доступная память: free + inactive + speculative (как в `app/presets.py`)."""

    if not text:
        return None
    page = None
    for line in text.splitlines():
        if "page size of" in line:
            digits = "".join(ch for ch in line.split("page size of")[1] if ch.isdigit())
            page = int(digits) if digits else None
            break
    if page is None:
        return None
    pages = 0
    for counter in PAGE_COUNTERS:
        value = None
        for line in text.splitlines():
            if line.startswith(counter + ":"):
                digits = "".join(ch for ch in line.split(":", 1)[1] if ch.isdigit())
                value = int(digits) if digits else None
                break
        if value is None:
            return None
        pages += value
    return pages * page


def parse_total_memory(text: str | None) -> int | None:
    if not text or not text.strip().isdigit():
        return None
    return int(text.strip())


class Probes:
    """Системные пробы. `runner` подменяется в тестах, реальный GPU не нужен."""

    def __init__(
        self,
        *,
        helper: Path | None = DEFAULT_HELPER,
        runner: CommandRunner = run_command,
        timeout: float = 3.0,
    ) -> None:
        self.helper = helper
        self.runner = runner
        self.timeout = timeout

    def _run(self, command: list[str]) -> str | None:
        try:
            return self.runner(command)
        except OSError:
            return None

    def thermal(self) -> ThermalReading:
        if self.helper is None:
            return ThermalReading("unknown", "none")
        if not Path(self.helper).exists():
            return ThermalReading("unknown", "missing")
        text = self._run([str(self.helper)])
        if text is None:
            return ThermalReading("unknown", "failed")
        return parse_thermal(text)

    def power(self) -> PowerReading:
        return parse_power(self._run(["pmset", "-g", "ps"]))

    def memory(self) -> MemoryReading:
        level = parse_pressure_level(
            self._run(["sysctl", "-n", "kern.memorystatus_vm_pressure_level"])
        )
        available = parse_vm_stat(self._run(["vm_stat"]))
        pressure = PRESSURE_NAMES.get(level or 0, "unknown")
        return MemoryReading(pressure, level, available)

    def low_power_mode(self) -> bool | None:
        return parse_low_power_mode(self._run(["pmset", "-g"]))

    def total_memory_bytes(self) -> int | None:
        return parse_total_memory(self._run(["sysctl", "-n", "hw.memsize"]))


def build_helper(source: Path = HELPER_SOURCE, target: Path = DEFAULT_HELPER) -> Path:
    """Собирает Swift-helper локально (`swiftc`), без зависимостей и сети."""

    if not source.exists():
        raise FileNotFoundError(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        ["swiftc", "-O", "-o", str(target), str(source)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "swiftc завершился с ошибкой")
    return target


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """Атомарная запись: падение воркера не оставит обрезанный JSON."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
    os.replace(temporary, path)


class EventLog:
    """JSONL-журнал решений с ротацией по размеру (Q-35)."""

    def __init__(
        self,
        path: Path = DEFAULT_LOG_FILE,
        *,
        max_bytes: int = 5 * 1024 * 1024,
        backups: int = 2,
    ) -> None:
        self.path = path
        self.max_bytes = max_bytes
        self.backups = backups

    def rotate_if_needed(self) -> None:
        try:
            size = self.path.stat().st_size
        except OSError:
            return
        if size < self.max_bytes:
            return
        try:
            for index in range(self.backups, 0, -1):
                source = (
                    self.path
                    if index == 1
                    else self.path.with_name(f"{self.path.name}.{index - 1}")
                )
                target = self.path.with_name(f"{self.path.name}.{index}")
                if source.exists():
                    os.replace(source, target)
        except OSError as error:
            print(f"warning: ротация {self.path} не удалась: {error}", file=sys.stderr)

    def write(self, record: dict[str, Any]) -> None:
        self.rotate_if_needed()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as error:
            print(f"warning: не удалось записать {self.path}: {error}", file=sys.stderr)


class KeepAwake:
    """`caffeinate -i` на время активного шага рендера (Q-31).

    `-w <pid>` привязывает процесс к воркеру: при падении воркера caffeinate
    завершается сам, orphan-процессов не остаётся. Явный `stop()` вызывается
    из `finally` после рендера.
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        popen: Callable[..., Any] = subprocess.Popen,
        pid: int | None = None,
    ) -> None:
        self.enabled = enabled
        self.popen = popen
        self.pid = pid or os.getpid()
        self.process: Any | None = None

    def start(self) -> None:
        if not self.enabled or self.process is not None:
            return
        try:
            self.process = self.popen(
                ["caffeinate", "-i", "-w", str(self.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as error:
            print(f"warning: caffeinate не запущен: {error}", file=sys.stderr)

    def stop(self) -> None:
        if self.process is None:
            return
        try:
            self.process.terminate()
            self.process.wait(timeout=5)
        except (OSError, subprocess.SubprocessError):
            pass
        self.process = None

    def __enter__(self) -> "KeepAwake":
        self.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.stop()


class ThermalGate:
    """Допуск к следующей тяжёлой job и учёт cooldown между шотами."""

    def __init__(
        self,
        *,
        profile: str = "balanced",
        worker_name: str = "ltx-1",
        state_path: Path = DEFAULT_STATE_FILE,
        log_path: Path = DEFAULT_LOG_FILE,
        probes: Probes | None = None,
        now: Callable[[], datetime] = utcnow,
        poll_seconds: float = 60.0,
        max_wait_seconds: float = 21600.0,
        allow_battery: bool = False,
        cooldown_between_s: float | None = None,
        cooldown_after_batch_s: float | None = None,
        batch_size: int | None = None,
    ) -> None:
        if profile not in PROFILES:
            raise ValueError(f"unknown thermal profile: {profile}")
        base = PROFILES[profile]
        overrides: dict[str, Any] = {}
        if cooldown_between_s is not None:
            overrides["cooldown_between_s"] = cooldown_between_s
        if cooldown_after_batch_s is not None:
            overrides["cooldown_after_batch_s"] = cooldown_after_batch_s
        if batch_size is not None:
            overrides["batch_size"] = max(1, batch_size)
        self.profile: Profile = replace(base, **overrides) if overrides else base
        self.worker_name = worker_name
        self.state_path = state_path
        self.log = EventLog(log_path)
        self.probes = probes or Probes()
        self.now = now
        self.poll_seconds = poll_seconds
        self.max_wait_seconds = max_wait_seconds
        self.allow_battery = allow_battery

        state = _read_json(state_path)
        batch = state.get("batch") or {}
        cooldown = state.get("cooldown") or {}
        self._consecutive = int(
            batch.get("consecutive_jobs") or state.get("consecutive_jobs") or 0
        )
        self._next_allowed_at = parse_iso(
            cooldown.get("next_allowed_at") or state.get("next_allowed_at")
        )
        pause = state.get("pause") or {}
        self._pause_since = parse_iso(pause.get("since"))
        self._pause_reason = pause.get("reason") if isinstance(pause, dict) else None
        self._recovery_samples = int(state.get("recovery_samples") or 0)
        self._last_key: tuple[bool, str | None] | None = None
        self._last_touch: datetime | None = None
        self._rendering = False
        self._current_job_id: str | None = None
        self._last: Decision | None = None

    # --- допуск ---------------------------------------------------------

    def before_next(self) -> Decision:
        now = self.now()
        thermal = self.probes.thermal()
        power = self.probes.power()
        memory = self.probes.memory()
        decision = self._evaluate(now, thermal, power, memory)
        self._last = decision
        self._persist(now, decision, thermal, power, memory)
        self._log_decision(decision)
        return decision

    def _evaluate(
        self,
        now: datetime,
        thermal: ThermalReading,
        power: PowerReading,
        memory: MemoryReading,
    ) -> Decision:
        profile = self.profile
        common = {"thermal": thermal, "power": power, "memory": memory}
        if profile.name == "off":
            return Decision(True, "guard_disabled", **common)

        # 1. Перегрев: новые job не берутся, текущий рендер досчитывается.
        if thermal.state in ("serious", "critical"):
            self._recovery_samples = 0
            return Decision(
                False, f"thermal_{thermal.state}", self.poll_seconds, **common
            )

        # 2. Гистерезис: после перегрева ждём подряд `nominal` и выдержку.
        if self._awaiting_recovery():
            if thermal.state != "nominal":
                self._recovery_samples = 0
                return Decision(False, "thermal_recovery", self.poll_seconds, **common)
            self._recovery_samples += 1
            if self._recovery_samples < profile.recovery_samples:
                return Decision(False, "thermal_recovery", self.poll_seconds, **common)
            self._recovery_samples = 0
            self._pause_since = None
            self._pause_reason = None
            self._next_allowed_at = now + timedelta(seconds=profile.recovery_cooldown_s)

        # 3. Питание: Eco требует сеть; батарея — только с разрешением и зарядом.
        if profile.require_ac:
            if power.source == "battery":
                if not self.allow_battery:
                    return Decision(False, "power_not_ac", self.poll_seconds, **common)
                if power.battery_percent is None or (
                    power.battery_percent < MIN_BATTERY_PERCENT
                ):
                    return Decision(False, "battery_low", self.poll_seconds, **common)
            elif power.source != "ac":
                return Decision(False, "power_unknown", self.poll_seconds, **common)

        # 4. Память: нехватка — пауза, а не завершение работы (Q-30).
        if memory.pressure == "critical":
            return Decision(
                False, "memory_pressure_critical", self.poll_seconds, **common
            )
        if profile.require_normal_pressure and memory.pressure != "normal":
            return Decision(
                False, f"memory_pressure_{memory.pressure}", self.poll_seconds, **common
            )
        if (
            memory.available_bytes is not None
            and memory.available_bytes < profile.min_free_gib * GIB
        ):
            return Decision(False, "memory_low", self.poll_seconds, **common)

        # 5. Cooldown между шотами и партиями.
        if self._next_allowed_at is not None and now < self._next_allowed_at:
            remaining = (self._next_allowed_at - now).total_seconds()
            return Decision(
                False, "cooldown", max(1.0, min(remaining, self.poll_seconds)), **common
            )

        return Decision(True, None, 0.0, **common)

    def _awaiting_recovery(self) -> bool:
        return (
            self.profile.recovery_required
            and self._pause_since is not None
            and self._pause_reason in THERMAL_PAUSE_REASONS
        )

    # --- после рендера --------------------------------------------------

    def after_job(self, *, job_id: str | None = None, ok: bool = True) -> None:
        profile = self.profile
        now = self.now()
        self._rendering = False
        self._current_job_id = None
        thermal = self.probes.thermal()
        power = self.probes.power()
        memory = self.probes.memory()
        self.log.write(
            {
                "ts": iso(now),
                "event": "job_finished",
                "profile": profile.name,
                "worker": self.worker_name,
                "thermal": thermal.state,
                "power": power.source,
                "memory": memory.pressure,
                "reason": None if ok else "job_failed",
                "job_id": job_id,
            }
        )
        if profile.name == "off":
            self._persist(now, Decision(True, "guard_disabled"), thermal, power, memory)
            return

        cooldown = profile.cooldown_between_s
        batch_size = profile.batch_size
        if thermal.state == "fair" and cooldown:
            cooldown *= 2
        elif thermal.state == "unknown":
            # Не знаем тепло — работаем по консервативному расписанию (§5).
            cooldown = max(cooldown, profile.unknown_thermal_floor_s)
            batch_size = min(batch_size, 2)

        consecutive = self._consecutive + 1
        if consecutive >= batch_size:
            next_allowed = now + timedelta(
                seconds=max(profile.cooldown_after_batch_s, cooldown)
            )
            consecutive = 0
        else:
            next_allowed = now + timedelta(seconds=cooldown)
        self._consecutive = consecutive
        self._next_allowed_at = next_allowed if cooldown > 0 else None
        # Горячее состояние фиксируется сразу после рендера: снимок не должен
        # показывать «допуск разрешён» между завершением job и следующим опросом.
        blocked_reason = (
            f"thermal_{thermal.state}"
            if thermal.state in ("serious", "critical")
            else None
        )
        self._persist(
            now,
            Decision(
                blocked_reason is None,
                blocked_reason,
                thermal=thermal,
                power=power,
                memory=memory,
            ),
            thermal,
            power,
            memory,
        )

    # --- во время рендера ----------------------------------------------

    def touch(self, *, job_id: str | None = None) -> None:
        """Обновляет снимок во время рендера: статус не должен «стареть»."""

        now = self.now()
        self._rendering = True
        self._current_job_id = job_id or self._current_job_id
        if (
            self._last_touch is not None
            and (now - self._last_touch).total_seconds() < self.poll_seconds
        ):
            return
        self._last_touch = now
        thermal = self.probes.thermal()
        power = self.probes.power()
        memory = self.probes.memory()
        decision = Decision(
            True, "rendering", thermal=thermal, power=power, memory=memory
        )
        self._last = decision
        self._persist(now, decision, thermal, power, memory)

    def start_job(self, job_id: str | None = None) -> None:
        self._rendering = True
        self._current_job_id = job_id
        self._last_touch = None

    def job_telemetry(self) -> dict[str, object]:
        """Провенанс попытки: условия, в которых начался рендер."""

        thermal = self.probes.thermal()
        power = self.probes.power()
        memory = self.probes.memory()
        total = self.probes.total_memory_bytes()
        available_mb = (
            round(memory.available_bytes / 1024**2) if memory.available_bytes else None
        )
        peak = None
        if total is not None and memory.available_bytes is not None:
            peak = round((total - memory.available_bytes) / 1024**2)
        return {
            "profile": self.profile.name,
            "thermal_state": thermal.state,
            "thermal_source": thermal.source,
            "power_source": power.source,
            "battery_percent": power.battery_percent,
            "low_power_mode": self.probes.low_power_mode(),
            "memory_pressure": memory.pressure,
            "available_mb": available_mb,
            "min_available_mb": available_mb,
            "max_pressure_level": memory.pressure_level,
            "peak_mem_mb": peak,
            "memory_metric": "system_used_mb",
        }

    def sample(self, telemetry: dict[str, object]) -> None:
        """Обновляет минимум свободной памяти и пик занятой во время рендера."""

        memory = self.probes.memory()
        if memory.available_bytes is not None:
            available_mb = round(memory.available_bytes / 1024**2)
            previous = telemetry.get("min_available_mb")
            if not isinstance(previous, int) or available_mb < previous:
                telemetry["min_available_mb"] = available_mb
                total = self.probes.total_memory_bytes()
                if total is not None:
                    telemetry["peak_mem_mb"] = round(
                        (total - memory.available_bytes) / 1024**2
                    )
        if memory.pressure_level is not None:
            previous_level = telemetry.get("max_pressure_level")
            if not isinstance(previous_level, int) or (
                memory.pressure_level > previous_level
            ):
                telemetry["max_pressure_level"] = memory.pressure_level

    # --- ожидание -------------------------------------------------------

    def waited_seconds(self) -> float:
        if self._pause_since is None:
            return 0.0
        return max(0.0, (self.now() - self._pause_since).total_seconds())

    def should_stop_waiting(self) -> bool:
        return self.max_wait_seconds > 0 and self.waited_seconds() >= self.max_wait_seconds

    # --- состояние и журнал ---------------------------------------------

    def _persist(
        self,
        now: datetime,
        decision: Decision,
        thermal: ThermalReading | None,
        power: PowerReading | None,
        memory: MemoryReading | None,
    ) -> None:
        if decision.allowed:
            self._pause_since = None
            self._pause_reason = None
        elif self._pause_since is None and decision.reason != "cooldown":
            self._pause_since = now
            self._pause_reason = decision.reason

        next_allowed = self._next_allowed_at
        remaining = (
            max(0.0, (next_allowed - now).total_seconds()) if next_allowed else 0.0
        )
        payload = {
            "schema": 1,
            "worker": self.worker_name,
            "profile": self.profile.name,
            "pid": os.getpid(),
            "updated_at": iso(now),
            "rendering": self._rendering,
            "current_job_id": self._current_job_id,
            "thermal": (
                {"state": thermal.state, "source": thermal.source}
                if thermal is not None
                else None
            ),
            "power": (
                {
                    "source": power.source,
                    "battery_percent": power.battery_percent,
                }
                if power is not None
                else None
            ),
            "low_power_mode": self.probes.low_power_mode(),
            "memory": (
                {
                    "pressure": memory.pressure,
                    "pressure_level": memory.pressure_level,
                    "available_bytes": memory.available_bytes,
                }
                if memory is not None
                else None
            ),
            "admission": {
                "allowed": decision.allowed,
                "reason": decision.reason,
                "wait_seconds": round(decision.wait_seconds, 1),
            },
            "cooldown": {
                "next_allowed_at": iso(next_allowed) if next_allowed else None,
                "remaining_seconds": round(remaining, 1),
            },
            "pause": {
                "active": self._pause_since is not None,
                "reason": self._pause_reason,
                "since": iso(self._pause_since) if self._pause_since else None,
                "waited_seconds": round(self.waited_seconds(), 1),
            },
            "batch": {
                "index": self._consecutive,
                "size": self.profile.batch_size,
                "consecutive_jobs": self._consecutive,
            },
            "recovery_samples": self._recovery_samples,
        }
        try:
            _write_json(self.state_path, payload)
        except OSError as error:
            print(
                f"warning: не удалось записать {self.state_path}: {error}",
                file=sys.stderr,
            )

    def _log_decision(self, decision: Decision) -> None:
        key = (decision.allowed, decision.reason)
        if key == self._last_key:
            return
        self._last_key = key
        self.log.write(
            {
                "ts": iso(self.now()),
                "event": "decision",
                "profile": self.profile.name,
                "worker": self.worker_name,
                "thermal": decision.thermal.state,
                "power": decision.power.source,
                "memory": decision.memory.pressure,
                "reason": decision.reason,
                "job_id": None,
            }
        )

    def snapshot(self) -> dict[str, Any]:
        return _read_json(self.state_path)


class NullGate:
    """Пустой gate: пути, где thermal-контроль не подключён (тесты, dry-run)."""

    profile = Profile(name="off")

    def before_next(self) -> Decision:
        return Decision(True, "guard_disabled")

    def after_job(self, *, job_id: str | None = None, ok: bool = True) -> None:
        return None

    def touch(self, *, job_id: str | None = None) -> None:
        return None

    def start_job(self, job_id: str | None = None) -> None:
        return None

    def job_telemetry(self) -> dict[str, object]:
        return {}

    def sample(self, telemetry: dict[str, object]) -> None:
        return None

    def waited_seconds(self) -> float:
        return 0.0

    def should_stop_waiting(self) -> bool:
        return False

    def snapshot(self) -> dict[str, Any]:
        return {}
