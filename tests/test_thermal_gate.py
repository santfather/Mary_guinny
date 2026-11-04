"""WP-THERMAL-02: thermal-safe допуск воркера без GPU и реальных прогонов.

Все системные пробы подменены: thermal/power/memory приходят из заглушки,
время — из управляемых часов, поэтому тесты детерминированы.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKER_DIR = REPO_ROOT / "worker"
for path in (REPO_ROOT, WORKER_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import thermal  # noqa: E402
from thermal import (  # noqa: E402
    EventLog,
    KeepAwake,
    MemoryReading,
    PowerReading,
    Probes,
    ThermalGate,
    ThermalReading,
    parse_power,
    parse_pressure_level,
    parse_thermal,
    parse_vm_stat,
)

GIB = 1024**3
AC = PowerReading("ac", 100.0)
BATTERY = PowerReading("battery", 80.0)
BATTERY_LOW = PowerReading("battery", 42.0)
NORMAL = MemoryReading("normal", 1, 8 * GIB)
WARNING = MemoryReading("warning", 2, 8 * GIB)
CRITICAL = MemoryReading("critical", 4, 8 * GIB)
LOW_MEMORY = MemoryReading("normal", 1, 3 * GIB)


class Clock:
    def __init__(self, start: datetime | None = None) -> None:
        self.value = start or datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += timedelta(seconds=seconds)


class StubProbes(Probes):
    def __init__(
        self,
        *,
        thermal_state: str = "nominal",
        power: PowerReading = AC,
        memory: MemoryReading = NORMAL,
        total: int = 16 * GIB,
    ) -> None:
        super().__init__(helper=None)
        self.thermal_state = thermal_state
        self.power_reading = power
        self.memory_reading = memory
        self.total = total

    def thermal(self) -> ThermalReading:
        return ThermalReading(self.thermal_state, "process_info")

    def power(self) -> PowerReading:
        return self.power_reading

    def memory(self) -> MemoryReading:
        return self.memory_reading

    def total_memory_bytes(self) -> int | None:
        return self.total


def make_gate(
    tmp_path: Path,
    *,
    profile: str = "eco",
    probes: StubProbes | None = None,
    clock: Clock | None = None,
    **kwargs,
) -> ThermalGate:
    return ThermalGate(
        profile=profile,
        state_path=tmp_path / "thermal-state.json",
        log_path=tmp_path / "thermal-events.jsonl",
        probes=probes or StubProbes(),
        now=(clock or Clock()).now,
        poll_seconds=kwargs.pop("poll_seconds", 60.0),
        **kwargs,
    )


# --- матрица допуска ---------------------------------------------------


def test_off_profile_allows_without_checks(tmp_path: Path) -> None:
    gate = make_gate(
        tmp_path,
        profile="off",
        probes=StubProbes(thermal_state="critical", power=BATTERY, memory=CRITICAL),
    )
    decision = gate.before_next()
    assert decision.allowed
    assert decision.reason == "guard_disabled"


@pytest.mark.parametrize("state", ["serious", "critical"])
def test_hot_thermal_state_pauses(tmp_path: Path, state: str) -> None:
    gate = make_gate(tmp_path, probes=StubProbes(thermal_state=state))
    decision = gate.before_next()
    assert not decision.allowed
    assert decision.reason == f"thermal_{state}"
    assert decision.wait_seconds == 60.0


def test_fair_and_nominal_allow_new_job(tmp_path: Path) -> None:
    for state in ("fair", "nominal"):
        gate = make_gate(tmp_path, probes=StubProbes(thermal_state=state))
        assert gate.before_next().allowed


def test_eco_requires_ac_power(tmp_path: Path) -> None:
    gate = make_gate(tmp_path, probes=StubProbes(power=BATTERY))
    decision = gate.before_next()
    assert not decision.allowed
    assert decision.reason == "power_not_ac"


def test_eco_battery_needs_permission_and_charge(tmp_path: Path) -> None:
    low = make_gate(
        tmp_path, probes=StubProbes(power=BATTERY_LOW), allow_battery=True
    )
    assert low.before_next().reason == "battery_low"

    enough = make_gate(
        tmp_path, probes=StubProbes(power=BATTERY), allow_battery=True
    )
    assert enough.before_next().allowed


def test_eco_unconfirmed_power_source_is_blocked(tmp_path: Path) -> None:
    gate = make_gate(tmp_path, probes=StubProbes(power=PowerReading("unknown")))
    assert gate.before_next().reason == "power_unknown"


def test_balanced_does_not_require_ac(tmp_path: Path) -> None:
    gate = make_gate(tmp_path, profile="balanced", probes=StubProbes(power=BATTERY))
    assert gate.before_next().allowed


@pytest.mark.parametrize(
    ("memory", "reason"),
    [
        (WARNING, "memory_pressure_warning"),
        (CRITICAL, "memory_pressure_critical"),
        (LOW_MEMORY, "memory_low"),
    ],
)
def test_eco_memory_checks(
    tmp_path: Path, memory: MemoryReading, reason: str
) -> None:
    gate = make_gate(tmp_path, probes=StubProbes(memory=memory))
    decision = gate.before_next()
    assert not decision.allowed
    assert decision.reason == reason


def test_memory_pause_is_not_a_stop(tmp_path: Path) -> None:
    """Q-30: нехватка памяти — пауза, процесс и рендер не завершаются."""

    probes = StubProbes(memory=LOW_MEMORY)
    gate = make_gate(tmp_path, probes=probes)
    decision = gate.before_next()
    assert not decision.allowed
    assert gate.snapshot()["pause"]["active"] is True

    probes.memory_reading = NORMAL
    assert gate.before_next().allowed


# --- cooldown и партия -------------------------------------------------


def test_unknown_thermal_uses_conservative_cooldown(tmp_path: Path) -> None:
    clock = Clock()
    gate = make_gate(
        tmp_path,
        profile="balanced",
        probes=StubProbes(thermal_state="unknown"),
        clock=clock,
    )
    gate.after_job(job_id="j1")
    state = gate.snapshot()
    next_allowed = datetime.fromisoformat(state["cooldown"]["next_allowed_at"])
    assert (next_allowed - clock.now()).total_seconds() == 900.0
    assert state["batch"]["size"] == 3  # профиль не меняется, сокращается партия


def test_unknown_thermal_batch_shrinks_to_two(tmp_path: Path) -> None:
    clock = Clock()
    gate = make_gate(
        tmp_path,
        profile="balanced",
        probes=StubProbes(thermal_state="unknown"),
        clock=clock,
    )
    gate.after_job(job_id="j1")
    clock.advance(1000)
    gate.after_job(job_id="j2")
    state = gate.snapshot()
    assert state["batch"]["consecutive_jobs"] == 0
    next_allowed = datetime.fromisoformat(state["cooldown"]["next_allowed_at"])
    assert (next_allowed - clock.now()).total_seconds() == 1200.0


def test_fair_doubles_cooldown(tmp_path: Path) -> None:
    clock = Clock()
    gate = make_gate(
        tmp_path,
        profile="balanced",
        probes=StubProbes(thermal_state="fair"),
        clock=clock,
    )
    gate.after_job(job_id="j1")
    next_allowed = datetime.fromisoformat(
        gate.snapshot()["cooldown"]["next_allowed_at"]
    )
    assert (next_allowed - clock.now()).total_seconds() == 960.0


def test_batch_cooldown_and_reset(tmp_path: Path) -> None:
    clock = Clock()
    gate = make_gate(tmp_path, probes=StubProbes(), clock=clock)
    gate.after_job(job_id="j0")
    clock.advance(1000)
    gate.after_job(job_id="j1")
    clock.advance(1000)
    gate.after_job(job_id="j2")
    state = gate.snapshot()
    assert state["batch"]["consecutive_jobs"] == 0
    next_allowed = datetime.fromisoformat(state["cooldown"]["next_allowed_at"])
    assert (next_allowed - clock.now()).total_seconds() == 1200.0


def test_cooldown_blocks_until_next_allowed(tmp_path: Path) -> None:
    clock = Clock()
    gate = make_gate(tmp_path, probes=StubProbes(), clock=clock)
    gate.after_job(job_id="j1")

    blocked = gate.before_next()
    assert not blocked.allowed
    assert blocked.reason == "cooldown"
    assert blocked.wait_seconds == 60.0  # не больше poll_seconds

    clock.advance(480)
    assert gate.before_next().allowed


def test_cooldown_survives_restart(tmp_path: Path) -> None:
    clock = Clock()
    first = make_gate(tmp_path, probes=StubProbes(), clock=clock)
    first.after_job(job_id="j1")

    clock.advance(60)
    second = make_gate(tmp_path, probes=StubProbes(), clock=clock)
    decision = second.before_next()
    assert decision.reason == "cooldown"
    remaining = datetime.fromisoformat(
        second.snapshot()["cooldown"]["next_allowed_at"]
    )
    assert (remaining - clock.now()).total_seconds() == 420.0


# --- восстановление после перегрева ------------------------------------


def test_thermal_recovery_needs_two_nominal_samples(tmp_path: Path) -> None:
    clock = Clock()
    probes = StubProbes(thermal_state="serious")
    gate = make_gate(tmp_path, probes=probes, clock=clock)

    assert gate.before_next().reason == "thermal_serious"

    probes.thermal_state = "nominal"
    clock.advance(60)
    assert gate.before_next().reason == "thermal_recovery"

    clock.advance(60)
    assert gate.before_next().reason == "cooldown"

    clock.advance(600)
    assert gate.before_next().allowed


def test_thermal_pause_survives_worker_restart(tmp_path: Path) -> None:
    """Q-30/Q-32: пауза и гистерезис переживают рестарт воркера."""

    clock = Clock()
    probes = StubProbes(thermal_state="serious")
    first = make_gate(tmp_path, probes=probes, clock=clock)
    assert first.before_next().reason == "thermal_serious"
    assert first.snapshot()["pause"]["active"] is True

    probes.thermal_state = "nominal"
    clock.advance(60)
    second = make_gate(tmp_path, probes=probes, clock=clock)
    assert second.snapshot()["pause"]["active"] is True
    assert second.before_next().reason == "thermal_recovery"

    clock.advance(60)
    assert second.before_next().reason == "cooldown"
    clock.advance(600)
    assert second.before_next().allowed


def test_power_pause_clears_when_power_returns(tmp_path: Path) -> None:
    probes = StubProbes(power=BATTERY)
    gate = make_gate(tmp_path, probes=probes)
    assert gate.before_next().reason == "power_not_ac"

    probes.power_reading = AC
    assert gate.before_next().allowed
    assert gate.snapshot()["pause"]["active"] is False


def test_should_stop_waiting_after_max_wait(tmp_path: Path) -> None:
    clock = Clock()
    gate = make_gate(
        tmp_path,
        probes=StubProbes(thermal_state="serious"),
        clock=clock,
        max_wait_seconds=120,
    )
    assert not gate.should_stop_waiting()
    gate.before_next()
    clock.advance(121)
    assert gate.should_stop_waiting()


# --- источники и парсеры -----------------------------------------------


def test_parse_thermal_values() -> None:
    assert parse_thermal('{"state": "nominal"}').state == "nominal"
    assert parse_thermal('{"state": "SERIOUS", "source": "process_info"}') == (
        ThermalReading("serious", "process_info")
    )
    assert parse_thermal("").state == "unknown"
    assert parse_thermal("").source == "none"
    assert parse_thermal("not json").state == "unknown"
    assert parse_thermal('{"state": "hot"}').state == "unknown"


def test_missing_helper_is_unknown(tmp_path: Path) -> None:
    probes = Probes(helper=tmp_path / "no-helper", runner=lambda _: "unused")
    assert probes.thermal() == ThermalReading("unknown", "missing")


def test_helper_failure_is_unknown(tmp_path: Path) -> None:
    helper = tmp_path / "helper"
    helper.write_text("#!/bin/sh\n", encoding="utf-8")
    helper.chmod(0o755)
    probes = Probes(helper=helper, runner=lambda _: None)
    assert probes.thermal() == ThermalReading("unknown", "failed")


def test_parse_power_output() -> None:
    ac = parse_power("Now drawing from 'AC Power'\n -InternalBattery-0\t98%; charged")
    assert ac == PowerReading("ac", 98.0)
    battery = parse_power("Now drawing from 'Battery Power'\n -InternalBattery-0\t42%; discharging")
    assert battery == PowerReading("battery", 42.0)
    assert parse_power("") == PowerReading("unknown", None)


def test_parse_memory_outputs() -> None:
    assert parse_pressure_level("1\n") == 1
    assert parse_pressure_level("not-a-number") is None
    vm_stat = (
        "Mach Virtual Memory Statistics: (page size of 16384 bytes)\n"
        "Pages free:                               1000.\n"
        "Pages active:                             5000.\n"
        "Pages inactive:                           2000.\n"
        "Pages speculative:                         500.\n"
    )
    assert parse_vm_stat(vm_stat) == (1000 + 2000 + 500) * 16384
    assert parse_vm_stat(None) is None


# --- журнал и caffeinate -----------------------------------------------


def test_event_log_rotates(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "events.jsonl", max_bytes=200, backups=2)
    for index in range(20):
        log.write({"event": "decision", "index": index})
    assert (tmp_path / "events.jsonl").exists()
    assert (tmp_path / "events.jsonl.1").exists()
    # Ротация не даёт файлу расти безгранично.
    assert (tmp_path / "events.jsonl").stat().st_size <= 200 * 2


def test_event_log_records_fixed_fields(tmp_path: Path) -> None:
    gate = make_gate(tmp_path, probes=StubProbes(thermal_state="serious"))
    gate.before_next()
    record = json.loads(
        (tmp_path / "thermal-events.jsonl").read_text("utf-8").splitlines()[-1]
    )
    assert set(record) == {
        "ts",
        "event",
        "profile",
        "worker",
        "thermal",
        "power",
        "memory",
        "reason",
        "job_id",
    }
    assert record["reason"] == "thermal_serious"


def test_keep_awake_uses_caffeinate_and_stops() -> None:
    calls: list[list[str]] = []
    terminated: list[bool] = []

    class Process:
        def terminate(self) -> None:
            terminated.append(True)

        def wait(self, timeout: float) -> None:
            pass

    def popen(command: list[str], **kwargs) -> Process:
        calls.append(command)
        return Process()

    awake = KeepAwake(popen=popen, pid=4242)
    awake.start()
    awake.start()  # повторный запуск не создаёт второй процесс
    awake.stop()
    awake.stop()

    assert calls == [["caffeinate", "-i", "-w", "4242"]]
    assert terminated == [True]


def test_keep_awake_disabled_does_nothing() -> None:
    calls: list[list[str]] = []
    KeepAwake(enabled=False, popen=lambda command, **_: calls.append(command)).start()
    assert calls == []


# --- телеметрия --------------------------------------------------------


def test_job_telemetry_and_sample(tmp_path: Path) -> None:
    probes = StubProbes(memory=MemoryReading("normal", 1, 8 * GIB), total=16 * GIB)
    gate = make_gate(tmp_path, probes=probes)
    telemetry = gate.job_telemetry()
    assert telemetry["profile"] == "eco"
    assert telemetry["thermal_state"] == "nominal"
    assert telemetry["peak_mem_mb"] == 8 * 1024
    assert telemetry["min_available_mb"] == 8 * 1024

    probes.memory_reading = MemoryReading("warning", 2, 4 * GIB)
    gate.sample(telemetry)
    assert telemetry["min_available_mb"] == 4 * 1024
    assert telemetry["peak_mem_mb"] == 12 * 1024
    assert telemetry["max_pressure_level"] == 2


def test_snapshot_has_freshness_fields(tmp_path: Path) -> None:
    clock = Clock()
    gate = make_gate(tmp_path, probes=StubProbes(), clock=clock)
    gate.before_next()
    state = gate.snapshot()
    assert state["updated_at"] == "2026-11-04T12:00:00+00:00"
    assert state["profile"] == "eco"
    assert state["thermal"] == {"state": "nominal", "source": "process_info"}
    assert state["admission"]["allowed"] is True
