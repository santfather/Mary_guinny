"""WP-N3: LTX-воркер — сборка payload, lease-heartbeat, загрузка артефакта.

Сеть и ComfyUI подменяются: проверяется только оркестрация протокола.
Реальный рендер проверяется отдельно калибровочным прогоном.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKER_DIR = REPO_ROOT / "worker"
for path in (REPO_ROOT, WORKER_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import ltx_worker  # noqa: E402
from pipeline.comfyui.client import ComfyUIClient  # noqa: E402

PROMPT = "the cat blinks slowly and twitches an ear, static camera"
START_BYTES = b"approved-start-frame"
START_SHA = hashlib.sha256(START_BYTES).hexdigest()


class FakeComfy(ComfyUIClient):
    """Настоящий клиент с подменёнными сетевыми методами."""

    def __init__(
        self,
        *,
        available: bool = True,
        history: dict | None = None,
        history_entry: dict | None = None,
        queued_prompt: bool = False,
        pending_polls: int = 0,
        drop_queue_after: int | None = None,
        video: bytes = b"fake-mp4",
        polls: int = 3,
    ) -> None:
        super().__init__("http://comfy.test")
        self.available = available
        self.history = (
            history
            if history is not None
            else {
                "outputs": {
                    "3": {
                        "images": [
                            {"filename": "nlb_00001.mp4", "subfolder": "nlb", "type": "output"}
                        ]
                    }
                }
            }
        )
        self.history_entry = history_entry
        self.queued_prompt = queued_prompt
        # Сколько первых запросов `/history` отвечают «ещё не готово» и когда
        # prompt перестаёт быть в `/queue` (WP-M4: рендер ещё идёт / потерян).
        self.pending_polls = pending_polls
        self.drop_queue_after = drop_queue_after
        self.history_calls = 0
        self.queue_checks = 0
        self.video = video
        self.polls = polls
        self.queued: dict | None = None
        self.uploaded: tuple[Path, str] | None = None
        self.viewed: tuple[str, str, str] | None = None
        self.history_prompt: str | None = None

    async def is_available(self) -> bool:
        return self.available

    async def upload_image(self, image_path: Path, subfolder: str = "mary_guiness") -> dict[str, str]:
        self.uploaded = (image_path, subfolder)
        return {"name": "start.png", "subfolder": subfolder}

    async def queue_prompt(self, workflow: dict, client_id: str | None = None) -> str:
        self.queued = workflow
        return "prompt-1"

    async def get_history(self, prompt_id: str) -> dict | None:
        self.history_prompt = prompt_id
        self.history_calls += 1
        if self.history_calls <= self.pending_polls:
            return None
        return self.history_entry

    async def is_queued(self, prompt_id: str) -> bool:
        self.queue_checks += 1
        if self.drop_queue_after is not None and self.queue_checks > self.drop_queue_after:
            return False
        return self.queued_prompt

    async def wait_for_prompt(
        self, prompt_id: str, poll_interval: float = 2.0, *, timeout=None, on_poll=None
    ) -> dict:
        for _ in range(self.polls):
            if on_poll is not None:
                on_poll()
        return self.history

    async def get_image(
        self, filename: str, subfolder: str = "", folder_type: str = "output"
    ) -> bytes:
        self.viewed = (filename, subfolder, folder_type)
        return self.video


class StubApi:
    """Подменяет WorkerClient: фиксирует вызовы."""

    def __init__(self, start_image: bytes = START_BYTES, *, complete_error=None) -> None:
        self.start_image = start_image
        self.complete_error = complete_error
        self.resume_jobs: list[dict] = []
        self.calls: list[tuple] = []

    def download(self, content_url: str, destination: Path) -> str:
        destination.write_bytes(self.start_image)
        return hashlib.sha256(self.start_image).hexdigest()

    def heartbeat(self, job_id, worker_name, *, progress=None, stage=None, lease_seconds=60):
        self.calls.append(("heartbeat", stage, progress, lease_seconds))
        return {"status": "running"}

    def link_external(self, job_id, worker_name, external_id):
        self.calls.append(("external", job_id, worker_name, external_id))
        return {"job_id": job_id, "status": "leased", "external_id": external_id}

    def resume(self, worker_name):
        self.calls.append(("resume", worker_name))
        return {"worker_id": "worker-1", "jobs": list(self.resume_jobs)}

    def upload_artifact(self, job_id, worker_name, kind, source, mime_type):
        self.calls.append(("upload", kind, mime_type, source.read_bytes()))
        return {"id": "artifact-1"}

    def complete(self, job_id, worker_name, **kwargs):
        self.calls.append(("complete", kwargs))
        if self.complete_error is not None:
            raise self.complete_error
        return {"job_id": job_id, "status": "completed"}

    def fail(self, job_id, worker_name, error_code, *, retryable=False, message=None):
        self.calls.append(("fail", error_code, retryable, message))
        return {"job_id": job_id, "status": "failed", "error_code": error_code}

    def stages(self) -> list[str]:
        return [call[1] for call in self.calls if call[0] == "heartbeat"]


def _node_inputs(workflow: dict, class_type: str) -> dict:
    return next(
        node["inputs"] for node in workflow.values() if node.get("class_type") == class_type
    )


def _job(**overrides) -> "ltx_worker.ClaimedJob":
    inputs: dict[str, object] = {
        "prompt": PROMPT,
        "frames": 193,
        "fps": 24,
        "seed": 101,
        "shot_key": "NLB-01",
        "start_image": {
            "sha256": START_SHA,
            "content_url": "/api/artifacts/frame/content",
        },
    }
    inputs.update(overrides)
    return ltx_worker.ClaimedJob(
        job_id="job-1",
        attempt_id="attempt-1",
        kind="render_video",
        inputs=inputs,
        output_prefix="projects/p/shots/s/attempts/a/",
    )


@pytest.fixture(autouse=True)
def fake_probe(monkeypatch) -> None:
    monkeypatch.setattr(ltx_worker, "probe_duration", lambda path: (8.04, True))


@pytest.fixture(autouse=True)
def fake_state(tmp_path, monkeypatch) -> Path:
    """WP-M4: тесты не должны писать в настоящий `~/.mary-studio`."""

    path = tmp_path / "state.json"
    monkeypatch.setattr(ltx_worker, "DEFAULT_STATE_FILE", path)
    return path


def test_process_one_renders_and_completes() -> None:
    api = StubApi()
    comfy = FakeComfy()

    result = ltx_worker.process_one(api, _job(), "ltx-1", comfy=comfy)

    assert result["status"] == "completed"
    assert result["artifact_id"] == "artifact-1"

    assert comfy.queued is not None
    inputs = _node_inputs(comfy.queued, "LTX2MLXGenerate")
    assert inputs["prompt"] == PROMPT
    assert _node_inputs(comfy.queued, "LoadImage")["image"] == "mary_guiness/start.png"
    assert (inputs["width"], inputs["height"]) == (1080, 1920)
    assert inputs["num_frames"] == 193
    assert inputs["frame_rate"] == 24.0
    assert inputs["seed"] == 101
    assert inputs["filename_prefix"] == "nlb/NLB-01/attempt-1"
    assert comfy.uploaded is not None and comfy.uploaded[1] == "mary_guiness"
    assert comfy.viewed == ("nlb_00001.mp4", "nlb", "output")

    assert api.stages() == ["prepare", "sampling", "sampling", "sampling", "upload"]
    assert {call[3] for call in api.calls if call[0] == "heartbeat"} == {300}

    uploads = [call for call in api.calls if call[0] == "upload"]
    assert len(uploads) == 1
    assert uploads[0][1:3] == ("video", "video/mp4")

    complete = [call for call in api.calls if call[0] == "complete"][0][1]
    assert complete["workflow_version"].startswith("ltx23-mlx-q4-i2v/")
    assert complete["model_hash"] == "dgrauet/ltx-2.3-mlx-q4"
    assert complete["seed"] == 101
    assert complete["native_fps"] == 24.0
    assert complete["duration_s"] == pytest.approx(8.04)

    parameters = complete["parameters"]
    assert parameters["seed"] == 101
    assert (parameters["width"], parameters["height"]) == (1080, 1920)
    assert parameters["aspect_ratio"] == "9:16"
    assert parameters["num_frames"] == 193
    assert parameters["cfg_scale"] == pytest.approx(3.0)
    assert parameters["workflow_snapshot"] == comfy.queued


def test_process_one_requires_start_image() -> None:
    api = StubApi()
    comfy = FakeComfy()

    result = ltx_worker.process_one(api, _job(start_image=None), "ltx-1", comfy=comfy)

    assert result["error_code"] == "missing_start_image"
    assert comfy.queued is None
    assert [call[0] for call in api.calls] == ["fail"]


def test_process_one_requires_prompt() -> None:
    api = StubApi()
    comfy = FakeComfy()

    result = ltx_worker.process_one(api, _job(prompt="   "), "ltx-1", comfy=comfy)

    assert result["error_code"] == "missing_prompt"
    assert comfy.queued is None


def test_process_one_detects_start_image_mismatch() -> None:
    api = StubApi(start_image=b"tampered")

    result = ltx_worker.process_one(api, _job(), "ltx-1", comfy=FakeComfy())

    assert result["error_code"] == "start_image_sha256_mismatch"
    assert [call[0] for call in api.calls] == ["fail"]


def test_process_one_rejects_frames_not_matching_8k1() -> None:
    api = StubApi()

    result = ltx_worker.process_one(api, _job(frames=192), "ltx-1", comfy=FakeComfy())

    assert result["error_code"] == "frames_not_supported"


def test_process_one_reports_comfy_unavailable() -> None:
    api = StubApi()

    result = ltx_worker.process_one(api, _job(), "ltx-1", comfy=FakeComfy(available=False))

    assert result["error_code"] == "comfy_unavailable"
    fail_call = [call for call in api.calls if call[0] == "fail"][0]
    assert fail_call[2] is True


def test_process_one_reports_empty_comfy_output() -> None:
    api = StubApi()
    comfy = FakeComfy(history={"outputs": {}})

    result = ltx_worker.process_one(api, _job(), "ltx-1", comfy=comfy)

    assert result["error_code"] == "comfy_no_output"


def test_process_one_reports_comfy_execution_error() -> None:
    api = StubApi()
    comfy = FakeComfy(
        history={
            "status": {"status_str": "error", "messages": [["execution_error", {"node": "3"}]]},
            "outputs": {},
        }
    )

    result = ltx_worker.process_one(api, _job(), "ltx-1", comfy=comfy)

    assert result["error_code"] == "comfy_error"


def test_process_one_reports_invalid_mp4(monkeypatch) -> None:
    monkeypatch.setattr(ltx_worker, "probe_duration", lambda path: (0.0, False))
    api = StubApi()

    result = ltx_worker.process_one(api, _job(), "ltx-1", comfy=FakeComfy())

    assert result["error_code"] == "invalid_output"
    assert not [call for call in api.calls if call[0] == "complete"]


def test_render_seed_prefers_job_value_and_is_deterministic() -> None:
    assert ltx_worker.render_seed("attempt-1", 42) == 42
    first = ltx_worker.render_seed("attempt-1", None)
    assert first == ltx_worker.render_seed("attempt-1", None)
    assert first != ltx_worker.render_seed("attempt-2", None)
    assert 0 <= first < 2**31


def test_main_requires_worker_token(monkeypatch) -> None:
    monkeypatch.delenv("MARY_WORKER_TOKEN", raising=False)
    with pytest.raises(SystemExit) as excinfo:
        ltx_worker.main(["--once"])
    assert excinfo.value.code == 2


def test_default_workflow_is_the_api_template() -> None:
    assert ltx_worker.DEFAULT_WORKFLOW.exists()
    assert ltx_worker.DEFAULT_WORKFLOW.name == "ltx23_mlx_q4_i2v.api.json"


def test_process_one_links_prompt_id_and_clears_state(fake_state) -> None:
    api = StubApi()

    result = ltx_worker.process_one(api, _job(), "ltx-1", comfy=FakeComfy())

    assert result["status"] == "completed"
    assert [call for call in api.calls if call[0] == "external"] == [
        ("external", "job-1", "ltx-1", "prompt-1")
    ]
    assert ltx_worker._load_state(fake_state) == {}


def test_process_one_keeps_state_when_complete_fails(fake_state) -> None:
    api = StubApi(complete_error=ltx_worker.WorkerError("server is down"))

    with pytest.raises(ltx_worker.WorkerError):
        ltx_worker.process_one(api, _job(), "ltx-1", comfy=FakeComfy())

    state = ltx_worker._load_state(fake_state)
    assert state["job-1"]["prompt_id"] == "prompt-1"
    assert state["job-1"]["workflow_version"].startswith("ltx23-mlx-q4-i2v/")


def test_recover_completes_render_without_new_prompt(fake_state) -> None:
    api = StubApi()
    api.resume_jobs = [
        {"job_id": "job-1", "status": "lease_expired", "external_id": "prompt-9"}
    ]
    ltx_worker._remember_prompt(
        fake_state,
        "job-1",
        {
            "prompt_id": "prompt-9",
            "native_fps": 24.0,
            "workflow_version": "ltx23-mlx-q4-i2v/abc",
            "model_hash": "dgrauet/ltx-2.3-mlx-q4",
            "seed": 101,
            "parameters": {"width": 576, "height": 1024},
        },
    )
    comfy = FakeComfy(
        history_entry={
            "outputs": {
                "3": {
                    "images": [
                        {"filename": "nlb_00001.mp4", "subfolder": "nlb", "type": "output"}
                    ]
                }
            }
        }
    )

    results = ltx_worker.recover(
        api, "ltx-1", ltx_worker.RenderSettings(state_path=fake_state), comfy=comfy
    )

    assert results == [
        {"job_id": "job-1", "status": "completed", "artifact_id": "artifact-1", "recovered": True}
    ]
    assert comfy.queued is None
    assert comfy.history_prompt == "prompt-9"
    assert comfy.viewed == ("nlb_00001.mp4", "nlb", "output")
    assert [call[0] for call in api.calls] == ["resume", "heartbeat", "upload", "complete"]

    complete = [call for call in api.calls if call[0] == "complete"][0][1]
    assert complete["workflow_version"] == "ltx23-mlx-q4-i2v/abc"
    assert complete["model_hash"] == "dgrauet/ltx-2.3-mlx-q4"
    assert complete["seed"] == 101
    assert complete["native_fps"] == 24.0
    assert complete["parameters"]["width"] == 576
    assert complete["parameters"]["recovered"] is True
    assert complete["parameters"]["prompt_id"] == "prompt-9"
    assert ltx_worker._load_state(fake_state) == {}


def test_recover_fails_when_prompt_is_lost(fake_state) -> None:
    api = StubApi()
    api.resume_jobs = [
        {"job_id": "job-1", "status": "lease_expired", "external_id": "prompt-9"}
    ]

    results = ltx_worker.recover(
        api, "ltx-1", ltx_worker.RenderSettings(state_path=fake_state), comfy=FakeComfy()
    )

    assert results[0]["error_code"] == "external_prompt_lost"
    fail_call = [call for call in api.calls if call[0] == "fail"][0]
    assert fail_call[1] == "external_prompt_lost"
    assert fail_call[2] is True
    assert not [call for call in api.calls if call[0] == "upload"]


def test_recover_waits_for_prompt_still_running(fake_state) -> None:
    api = StubApi()
    api.resume_jobs = [
        {"job_id": "job-1", "status": "running", "external_id": "prompt-9"}
    ]
    finished = {
        "outputs": {
            "3": {
                "images": [
                    {"filename": "nlb_00001.mp4", "subfolder": "nlb", "type": "output"}
                ]
            }
        }
    }
    comfy = FakeComfy(
        history_entry=finished, queued_prompt=True, pending_polls=3, polls=3
    )

    results = ltx_worker.recover(
        api,
        "ltx-1",
        ltx_worker.RenderSettings(state_path=fake_state, poll_interval=0.0),
        comfy=comfy,
    )

    assert results[0]["recovered"] is True
    assert comfy.queued is None
    assert comfy.history_prompt == "prompt-9"
    stages = [call[1] for call in api.calls if call[0] == "heartbeat"]
    # Один heartbeat перед проверкой и по одному на каждый опрос `/history`.
    assert stages == ["recover"] * (comfy.polls + 1)
    assert [call[0] for call in api.calls][-2:] == ["upload", "complete"]


def test_recover_fails_when_prompt_vanishes_from_queue(fake_state) -> None:
    api = StubApi()
    api.resume_jobs = [
        {"job_id": "job-1", "status": "running", "external_id": "prompt-9"}
    ]
    comfy = FakeComfy(
        history_entry=None,
        queued_prompt=True,
        pending_polls=10,
        drop_queue_after=2,
    )

    results = ltx_worker.recover(
        api,
        "ltx-1",
        ltx_worker.RenderSettings(state_path=fake_state, poll_interval=0.0),
        comfy=comfy,
    )

    assert results[0]["error_code"] == "external_prompt_lost"
    fail_call = [call for call in api.calls if call[0] == "fail"][0]
    assert fail_call[1] == "external_prompt_lost"
    assert fail_call[2] is True
    assert not [call for call in api.calls if call[0] == "upload"]
    assert ltx_worker._load_state(fake_state) == {}


def test_recover_skips_jobs_without_prompt_and_drops_stale_state(fake_state) -> None:
    api = StubApi()
    api.resume_jobs = [{"job_id": "job-2", "status": "leased", "external_id": None}]
    ltx_worker._remember_prompt(fake_state, "job-old", {"prompt_id": "prompt-1"})

    results = ltx_worker.recover(
        api, "ltx-1", ltx_worker.RenderSettings(state_path=fake_state), comfy=FakeComfy()
    )

    assert results == []
    assert api.calls == [("resume", "ltx-1")]
    assert ltx_worker._load_state(fake_state) == {}


class SeriesApi:
    """Сервер серии: отдаёт заранее заданные ответы `series/next`."""

    def __init__(self, replies: list[dict]) -> None:
        self.replies = list(replies)
        self.next_calls: list[str | None] = []
        self.claims = 0
        self.pauses: list[str] = []
        self.resumes: list[str] = []

    def series_next(self, worker_name: str, *, run_id=None) -> dict:
        self.next_calls.append(run_id)
        return self.replies.pop(0)

    def claim(self, worker_name, *, lease_seconds=60, kinds=None):
        self.claims += 1
        return _job()

    def series_pause(self, run_id: str) -> dict:
        self.pauses.append(run_id)
        return {"status": "paused"}

    def series_resume(self, run_id: str) -> dict:
        self.resumes.append(run_id)
        return {"status": "running"}


def _series_args(**overrides):
    values = dict(name="ltx-1", lease=300, poll=0.0, once=False, series_run="run-1")
    values.update(overrides)
    return argparse.Namespace(**values)


def _stub_render(monkeypatch, processed: list[str]) -> None:
    def _process(api, job, worker_name, settings=None, *, comfy=None, gate=None):
        processed.append(job.job_id)
        return {"status": "completed"}

    monkeypatch.setattr(ltx_worker, "process_one", _process)


def test_series_loop_skips_blocked_items_and_renders_next(monkeypatch) -> None:
    processed: list[str] = []
    _stub_render(monkeypatch, processed)
    api = SeriesApi(
        [
            {"status": "skipped", "order": 1, "job_id": None, "reason": "missing_start_frame"},
            {"status": "queued", "order": 2, "job_id": "job-1"},
            {"status": "completed", "job_id": None, "counts": {}},
        ]
    )

    code = ltx_worker._series_loop(api, _series_args(), ltx_worker.RenderSettings())

    assert code == 0
    assert processed == ["job-1"]
    assert api.next_calls == ["run-1", "run-1", "run-1"]


def test_series_loop_returns_on_pause_without_claiming(monkeypatch) -> None:
    processed: list[str] = []
    _stub_render(monkeypatch, processed)
    api = SeriesApi(
        [{"status": "paused", "reason": "job_failed", "order": 1, "job_id": None}]
    )

    code = ltx_worker._series_loop(api, _series_args(), ltx_worker.RenderSettings())

    assert code == 0
    assert api.claims == 0
    assert processed == []


def test_series_loop_once_processes_single_job(monkeypatch) -> None:
    processed: list[str] = []
    _stub_render(monkeypatch, processed)
    api = SeriesApi([{"status": "queued", "order": 1, "job_id": "job-1"}])

    code = ltx_worker._series_loop(
        api, _series_args(once=True), ltx_worker.RenderSettings()
    )

    assert code == 0
    assert processed == ["job-1"]
    assert len(api.next_calls) == 1


def test_series_loop_warns_when_claim_returns_other_job(monkeypatch, capsys) -> None:
    processed: list[str] = []
    _stub_render(monkeypatch, processed)
    api = SeriesApi(
        [
            {"status": "queued", "order": 1, "job_id": "job-other"},
            {"status": "idle", "job_id": None},
        ]
    )

    code = ltx_worker._series_loop(api, _series_args(), ltx_worker.RenderSettings())

    assert code == 0
    assert processed == ["job-1"]
    assert "warning: claim вернул job-1" in capsys.readouterr().err


class StubGate:
    """Thermal-гейт с заданной последовательностью решений (WP-THERMAL-02)."""

    def __init__(self, allowed: list[bool], *, stop: bool = False) -> None:
        self.allowed = list(allowed)
        self.stop = stop
        self.pauses: list[str] = []
        self.after: list[tuple[str | None, bool]] = []
        self.profile = argparse.Namespace(name="balanced")

    def before_next(self):
        from thermal import Decision

        allowed = self.allowed.pop(0) if len(self.allowed) > 1 else bool(self.allowed[0])
        return Decision(allowed, None if allowed else "thermal_serious", 0.0)

    def start_job(self, job_id) -> None:
        pass

    def touch(self, *, job_id=None) -> None:
        pass

    def sample(self, telemetry) -> None:
        pass

    def after_job(self, *, job_id=None, ok=True) -> None:
        self.after.append((job_id, ok))

    def job_telemetry(self) -> dict:
        return {}

    def waited_seconds(self) -> float:
        return 0.0

    def should_stop_waiting(self) -> bool:
        return self.stop


def test_series_loop_thermal_block_pauses_and_resumes_run(monkeypatch) -> None:
    processed: list[str] = []
    _stub_render(monkeypatch, processed)
    monkeypatch.setattr(ltx_worker, "notify", lambda *a, **k: None)
    api = SeriesApi(
        [
            {"status": "queued", "order": 1, "job_id": "job-1"},
            {"status": "completed", "job_id": None, "counts": {}},
        ]
    )

    code = ltx_worker._series_loop(
        api, _series_args(), ltx_worker.RenderSettings(), StubGate([False, True])
    )

    assert code == 0
    assert processed == ["job-1"]
    assert api.pauses == ["run-1"]
    assert api.resumes == ["run-1"]


def test_series_loop_stops_waiting_after_thermal_timeout(monkeypatch) -> None:
    processed: list[str] = []
    _stub_render(monkeypatch, processed)
    monkeypatch.setattr(ltx_worker, "notify", lambda *a, **k: None)
    api = SeriesApi([])

    code = ltx_worker._series_loop(
        api, _series_args(), ltx_worker.RenderSettings(), StubGate([False], stop=True)
    )

    assert code == 1
    assert api.pauses == ["run-1"]
    assert api.claims == 0
    assert processed == []


def test_job_loop_does_not_claim_while_blocked(monkeypatch) -> None:
    api = SeriesApi([])

    code = ltx_worker._job_loop(
        api, _series_args(once=True), ltx_worker.RenderSettings(), StubGate([False])
    )

    assert code == 0
    assert api.claims == 0


def test_job_loop_stops_after_thermal_timeout(monkeypatch) -> None:
    """WP-THERMAL-03: вне серии ожидание тоже не бесконечное."""

    monkeypatch.setattr(ltx_worker, "notify", lambda *a, **k: None)
    api = SeriesApi([])

    code = ltx_worker._job_loop(
        api, _series_args(once=True), ltx_worker.RenderSettings(), StubGate([False], stop=True)
    )

    assert code == 1
    assert api.claims == 0


def test_build_thermal_gate_prefers_render_settings_profile(tmp_path) -> None:
    """T-06: профиль берётся из единого `RenderSettings`, а не из CLI-копии."""

    args = _thermal_args(
        thermal_profile="off",
        thermal_state_file=str(tmp_path / "thermal.json"),
        thermal_log=str(tmp_path / "events.jsonl"),
        thermal_helper=str(tmp_path / "missing-helper"),
        caffeinate=False,
    )

    gate = ltx_worker._build_thermal_gate(args, "eco")

    assert gate.profile.name == "eco"


def test_build_thermal_gate_off_disables_control() -> None:
    gate = ltx_worker._build_thermal_gate(_thermal_args(thermal_profile="off"))

    assert gate.profile.name == "off"


def test_build_thermal_gate_eco_uses_flags_and_warns(tmp_path, capsys) -> None:
    state = tmp_path / "thermal.json"
    args = _thermal_args(
        thermal_profile="eco",
        thermal_state_file=str(state),
        thermal_log=str(tmp_path / "events.jsonl"),
        thermal_helper=str(tmp_path / "missing-helper"),
        allow_battery=True,
        caffeinate=False,
    )

    gate = ltx_worker._build_thermal_gate(args)

    assert gate.profile.name == "eco"
    assert gate.allow_battery is True
    assert gate.state_path == state
    assert "thermal helper не найден" in capsys.readouterr().err


def _thermal_args(**overrides) -> argparse.Namespace:
    values = dict(
        name="ltx-1",
        thermal_profile="balanced",
        thermal_state_file="/tmp/thermal-state.json",
        thermal_log="/tmp/thermal-events.jsonl",
        thermal_helper="/tmp/thermal-helper",
        allow_battery=False,
        caffeinate=True,
        build_thermal_helper=False,
        thermal_poll=60.0,
        thermal_max_wait=21600.0,
    )
    values.update(overrides)
    return argparse.Namespace(**values)


def _presets_payload() -> dict[str, object]:
    return {
        "recommended": "safe",
        "reason": "рекомендован измеренный пресет safe (576×1024)",
        "presets": [
            {"name": "safe", "aspect_ratio": "9:16", "long_side": 1024, "cfg_scale": 3.0},
            {"name": "wide", "aspect_ratio": "16:9", "long_side": 1024, "cfg_scale": 3.0},
        ],
    }


def test_resolve_preset_uses_api_recommendation() -> None:
    choice = ltx_worker.resolve_preset(
        requested=None,
        aspect_ratio=None,
        long_side=None,
        cfg_scale=None,
        fetch=_presets_payload,
    )

    assert choice.preset == "safe"
    assert choice.source == "api"
    assert (choice.aspect_ratio, choice.long_side, choice.cfg_scale) == ("9:16", 1024, 3.0)
    assert choice.warning is None


def test_resolve_preset_explicit_flags_win_over_api() -> None:
    def fail_fetch() -> dict[str, object]:
        raise AssertionError("API не должен запрашиваться при явных флагах")

    choice = ltx_worker.resolve_preset(
        requested=None,
        aspect_ratio="16:9",
        long_side=1024,
        cfg_scale=None,
        fetch=fail_fetch,
    )

    assert choice.source == "cli"
    assert choice.preset is None
    assert choice.aspect_ratio == "16:9"
    assert choice.long_side == 1024
    assert choice.cfg_scale == ltx_worker.ltx_adapter.DEFAULT_CFG_SCALE


def test_resolve_preset_takes_named_preset_from_api() -> None:
    choice = ltx_worker.resolve_preset(
        requested="wide",
        aspect_ratio=None,
        long_side=None,
        cfg_scale=None,
        fetch=_presets_payload,
    )

    assert choice.preset == "wide"
    assert choice.source == "cli"
    assert choice.aspect_ratio == "16:9"
    assert choice.long_side == 1024


def test_resolve_preset_falls_back_when_api_is_unavailable() -> None:
    def boom() -> dict[str, object]:
        raise ltx_worker.WorkerError("GET /api/presets failed: connection refused")

    choice = ltx_worker.resolve_preset(
        requested=None,
        aspect_ratio=None,
        long_side=None,
        cfg_scale=None,
        fetch=boom,
    )

    assert choice.preset is None
    assert choice.source == "default"
    assert choice.long_side == ltx_worker.ltx_adapter.DEFAULT_LONG_SIDE
    assert choice.warning is not None and "пресет не получен" in choice.warning


def test_resolve_preset_reports_missing_recommendation() -> None:
    choice = ltx_worker.resolve_preset(
        requested=None,
        aspect_ratio=None,
        long_side=None,
        cfg_scale=None,
        fetch=lambda: {"recommended": None, "reason": "нужен Apple Silicon", "presets": []},
    )

    assert choice.source == "default"
    assert choice.preset is None
    assert choice.warning is not None and "нужен Apple Silicon" in choice.warning


def test_resolve_preset_reports_unknown_preset_name() -> None:
    choice = ltx_worker.resolve_preset(
        requested="quality",
        aspect_ratio=None,
        long_side=None,
        cfg_scale=None,
        fetch=_presets_payload,
    )

    assert choice.source == "default"
    assert choice.preset is None
    assert choice.warning is not None and "quality" in choice.warning


def test_process_one_records_preset_provenance() -> None:
    api = StubApi()
    settings = ltx_worker.RenderSettings(preset="safe", preset_source="api")

    result = ltx_worker.process_one(
        api, _job(), "ltx-1", settings=settings, comfy=FakeComfy()
    )

    assert result["status"] == "completed"
    complete = next(call[1] for call in api.calls if call[0] == "complete")
    assert complete["parameters"]["preset"] == "safe"
    assert complete["parameters"]["preset_source"] == "api"


def test_process_one_marks_preview_in_provenance() -> None:
    """T-07: preview-попытка отличается только флагом и числом кадров."""

    api = StubApi()

    ltx_worker.process_one(
        api,
        _job(preview=True, frames=73),
        "ltx-1",
        settings=ltx_worker.RenderSettings(),
        comfy=FakeComfy(),
    )

    complete = next(call[1] for call in api.calls if call[0] == "complete")
    assert complete["parameters"]["preview"] is True
    assert complete["parameters"]["num_frames"] == 73


def test_process_one_production_has_no_preview_flag() -> None:
    api = StubApi()

    ltx_worker.process_one(
        api, _job(), "ltx-1", settings=ltx_worker.RenderSettings(), comfy=FakeComfy()
    )

    complete = next(call[1] for call in api.calls if call[0] == "complete")
    assert "preview" not in complete["parameters"]

