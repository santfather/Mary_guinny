"""WP-06: FakeWorker — ffmpeg-генерация и обработка job без ComfyUI."""

from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

import pytest

WORKER_DIR = Path(__file__).resolve().parents[2] / "worker"
if str(WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(WORKER_DIR))

import fake_worker  # noqa: E402

from app.video_probe import probe_mp4  # noqa: E402

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
requires_ffmpeg = pytest.mark.skipif(
    FFMPEG is None or FFPROBE is None, reason="ffmpeg/ffprobe are not installed"
)


class StubClient:
    """Подменяет WorkerClient: фиксирует вызовы и отдаёт стартовый кадр."""

    def __init__(self, start_image: bytes) -> None:
        self.start_image = start_image
        self.calls: list[tuple] = []

    def download(self, content_url: str, destination: Path) -> str:
        destination.write_bytes(self.start_image)
        return hashlib.sha256(self.start_image).hexdigest()

    def heartbeat(self, job_id, worker_name, *, progress=None, stage=None, lease_seconds=60):
        self.calls.append(("heartbeat", stage, progress))
        return {"status": "running"}

    def upload_artifact(self, job_id, worker_name, kind, source, mime_type):
        self.calls.append(("upload", kind, mime_type, source.read_bytes()))
        return {"id": "artifact-1"}

    def complete(self, job_id, worker_name, **kwargs):
        self.calls.append(("complete", kwargs))
        return {"job_id": job_id, "status": "completed"}

    def fail(self, job_id, worker_name, error_code, *, retryable=False, message=None):
        self.calls.append(("fail", error_code, retryable))
        return {"job_id": job_id, "status": "failed", "error_code": error_code}


def _job(inputs: dict | None = None) -> "fake_worker.ClaimedJob":
    return fake_worker.ClaimedJob(
        job_id="job-1",
        attempt_id="attempt-1",
        kind="render_video",
        inputs=inputs or {},
        output_prefix="projects/p/shots/s/attempts/a/",
    )


def test_build_ffmpeg_command(tmp_path) -> None:
    target = tmp_path / "out.mp4"
    command = fake_worker.build_ffmpeg_command(target, frames=24, fps=12)

    assert command[0] == "ffmpeg"
    assert "-y" in command
    assert "libx264" in command
    assert "yuv420p" in command
    assert command[command.index("-i") + 1] == "color=c=0x3355aa:s=320x240:d=2.000:r=12"
    assert command[-1] == str(target)


@requires_ffmpeg
def test_generate_mp4_produces_valid_container(tmp_path) -> None:
    output = fake_worker.generate_mp4(
        tmp_path / "nested" / "output.mp4", frames=12, fps=12, size="160x120", ffmpeg=FFMPEG
    )
    info = probe_mp4(output.read_bytes())
    assert info.has_video is True
    assert info.duration_s == pytest.approx(1.0, abs=0.2)

    duration, has_video = fake_worker.probe_duration(output)
    assert has_video is True
    assert duration > 0


@requires_ffmpeg
def test_process_one_uploads_mp4_and_completes(tmp_path) -> None:
    start_image = b"fake-start-image"
    client = StubClient(start_image)
    job = _job(
        {
            "start_image": {
                "sha256": hashlib.sha256(start_image).hexdigest(),
                "content_url": "/api/artifacts/start/content",
            }
        }
    )

    result = fake_worker.process_one(
        client, job, "fake-1", frames=12, fps=12, ffmpeg=FFMPEG
    )

    assert result["status"] == "completed"
    assert result["artifact_id"] == "artifact-1"
    assert [call[1] for call in client.calls if call[0] == "heartbeat"] == [
        "prepare",
        "sampling",
        "upload",
    ]
    uploads = [call for call in client.calls if call[0] == "upload"]
    assert len(uploads) == 1
    assert uploads[0][1] == "video"
    assert uploads[0][2] == "video/mp4"
    info = probe_mp4(uploads[0][3])
    assert info.has_video is True
    assert info.duration_s > 0


def test_process_one_reports_start_image_mismatch() -> None:
    client = StubClient(b"actual-bytes")
    job = _job(
        {
            "start_image": {
                "sha256": "deadbeef",
                "content_url": "/api/artifacts/start/content",
            }
        }
    )

    result = fake_worker.process_one(client, job, "fake-1")

    assert result["status"] == "failed"
    assert client.calls == [("fail", "start_image_sha256_mismatch", False)]


def test_process_one_honours_forced_failure() -> None:
    client = StubClient(b"unused")

    result = fake_worker.process_one(client, _job(), "fake-1", force_fail="comfy_down")

    assert result["error_code"] == "comfy_down"
    assert client.calls == [("fail", "comfy_down", False)]


def test_main_requires_worker_token(monkeypatch) -> None:
    monkeypatch.delenv("MARY_WORKER_TOKEN", raising=False)
    with pytest.raises(SystemExit) as excinfo:
        fake_worker.main(["--once"])
    assert excinfo.value.code == 2
