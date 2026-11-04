from __future__ import annotations

from app import presets


def _hardware(**overrides: object) -> presets.Hardware:
    values: dict[str, object] = {
        "system": "Darwin",
        "machine": "arm64",
        "model": "Mac15,6",
        "chip": "Apple M3 Pro",
        "cpu_count": 12,
        "total_memory_bytes": 18 * presets.GIB,
        "available_memory_bytes": 8 * presets.GIB,
        "apple_silicon": True,
        "control_plane_only": False,
    }
    values.update(overrides)
    return presets.Hardware(**values)  # type: ignore[arg-type]


VM_STAT = """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                               1000.
Pages active:                              500.
Pages inactive:                           2000.
Pages speculative:                         300.
Pages wired down:                          400.
"""


def test_parse_vm_stat_counts_free_inactive_speculative() -> None:
    assert presets.parse_vm_stat(VM_STAT) == (1000 + 2000 + 300) * 16384


def test_parse_vm_stat_without_page_size_is_unknown() -> None:
    assert presets.parse_vm_stat("Pages free: 10.") is None


def test_parse_vm_stat_without_counter_is_unknown() -> None:
    text = "Mach Virtual Memory Statistics: (page size of 16384 bytes)\nPages free: 10.\n"
    assert presets.parse_vm_stat(text) is None


def test_detect_hardware_reads_sysctl_and_vm_stat(monkeypatch) -> None:
    mapping = {
        ("sysctl", "-n", "hw.model"): "Mac15,6",
        ("sysctl", "-n", "machdep.cpu.brand_string"): "Apple M3 Pro",
        ("sysctl", "-n", "hw.memsize"): str(18 * presets.GIB),
        ("vm_stat",): VM_STAT,
    }

    def fake_run(command: list[str]) -> str | None:
        return mapping.get(tuple(command))

    monkeypatch.setattr(presets, "_run", fake_run)
    monkeypatch.setattr(presets.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(presets.platform, "machine", lambda: "arm64")

    hardware = presets.detect_hardware()

    assert hardware.apple_silicon is True
    assert hardware.control_plane_only is False
    assert hardware.model == "Mac15,6"
    assert hardware.chip == "Apple M3 Pro"
    assert hardware.total_memory_bytes == 18 * presets.GIB
    assert hardware.available_memory_bytes == (1000 + 2000 + 300) * 16384


def test_detect_hardware_marks_non_apple_machine_as_control_plane(monkeypatch) -> None:
    monkeypatch.setattr(presets, "_run", lambda command: None)
    monkeypatch.setattr(presets.platform, "system", lambda: "Linux")
    monkeypatch.setattr(presets.platform, "machine", lambda: "x86_64")

    hardware = presets.detect_hardware()

    assert hardware.apple_silicon is False
    assert hardware.control_plane_only is True
    assert hardware.total_memory_bytes is None


def test_recommend_returns_measured_safe_on_apple_silicon() -> None:
    recommended, reason = presets.recommend(_hardware())

    assert recommended == "safe"
    assert "safe" in reason


def test_recommend_is_empty_on_control_plane() -> None:
    recommended, reason = presets.recommend(
        _hardware(machine="x86_64", apple_silicon=False, control_plane_only=True)
    )

    assert recommended is None
    assert "Apple Silicon" in reason


def test_recommend_is_empty_when_memory_is_too_low() -> None:
    recommended, reason = presets.recommend(
        _hardware(total_memory_bytes=8 * presets.GIB)
    )

    assert recommended is None
    assert "недостаточно памяти" in reason


def test_all_presets_are_measured_and_have_sizes() -> None:
    assert [preset.name for preset in presets.PRESETS] == ["safe", "wide", "legacy_512"]
    for preset in presets.PRESETS:
        assert preset.measured is True
        assert preset.measured_runs >= 1
        assert preset.width > 0 and preset.height > 0
        assert preset.long_side == max(preset.width, preset.height)


def test_presets_endpoint_reports_hardware_and_recommendation(api_client, monkeypatch) -> None:
    monkeypatch.setattr(presets, "detect_hardware", lambda: _hardware())

    response = api_client.get("/api/presets")

    assert response.status_code == 200
    payload = response.json()
    assert payload["recommended"] == "safe"
    assert [item["name"] for item in payload["presets"]] == [
        "safe",
        "wide",
        "legacy_512",
    ]
    safe = payload["presets"][0]
    assert (safe["width"], safe["height"]) == (576, 1024)
    assert safe["avg_render_seconds"] == 1062.5
    assert payload["hardware"]["total_memory_bytes"] == 18 * presets.GIB
    assert payload["hardware"]["apple_silicon"] is True


def test_presets_endpoint_has_no_recommendation_on_control_plane(api_client, monkeypatch) -> None:
    monkeypatch.setattr(
        presets,
        "detect_hardware",
        lambda: _hardware(machine="x86_64", apple_silicon=False, control_plane_only=True),
    )

    payload = api_client.get("/api/presets").json()

    assert payload["recommended"] is None
    assert "Apple Silicon" in payload["reason"]
