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
        self.video = video
        self.polls = polls
        self.queued: dict | None = None
        self.uploaded: tuple[Path, str] | None = None
        self.viewed: tuple[str, str, str] | None = None

    async def is_available(self) -> bool:
        return self.available

    async def upload_image(self, image_path: Path, subfolder: str = "mary_guiness") -> dict[str, str]:
        self.uploaded = (image_path, subfolder)
        return {"name": "start.png", "subfolder": subfolder}

    async def queue_prompt(self, workflow: dict, client_id: str | None = None) -> str:
        self.queued = workflow
        return "prompt-1"

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

    def __init__(self, start_image: bytes = START_BYTES) -> None:
        self.start_image = start_image
        self.calls: list[tuple] = []

    def download(self, content_url: str, destination: Path) -> str:
        destination.write_bytes(self.start_image)
        return hashlib.sha256(self.start_image).hexdigest()

    def heartbeat(self, job_id, worker_name, *, progress=None, stage=None, lease_seconds=60):
        self.calls.append(("heartbeat", stage, progress, lease_seconds))
        return {"status": "running"}

    def upload_artifact(self, job_id, worker_name, kind, source, mime_type):
        self.calls.append(("upload", kind, mime_type, source.read_bytes()))
        return {"id": "artifact-1"}

    def complete(self, job_id, worker_name, **kwargs):
        self.calls.append(("complete", kwargs))
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


class SeriesApi:
    """Сервер серии: отдаёт заранее заданные ответы `series/next`."""

    def __init__(self, replies: list[dict]) -> None:
        self.replies = list(replies)
        self.next_calls: list[str | None] = []
        self.claims = 0

    def series_next(self, worker_name: str, *, run_id=None) -> dict:
        self.next_calls.append(run_id)
        return self.replies.pop(0)

    def claim(self, worker_name, *, lease_seconds=60, kinds=None):
        self.claims += 1
        return _job()


def _series_args(**overrides):
    values = dict(name="ltx-1", lease=300, poll=0.0, once=False, series_run="run-1")
    values.update(overrides)
    return argparse.Namespace(**values)


def _stub_render(monkeypatch, processed: list[str]) -> None:
    def _process(api, job, worker_name, settings=None, *, comfy=None):
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
