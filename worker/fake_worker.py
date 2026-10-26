"""FakeWorker — реализация worker-протокола без ComfyUI (WP-06).

Тянет job через `POST /api/worker/claim`, скачивает стартовый кадр, генерирует
короткий валидный MP4 через ffmpeg, загружает артефакт и завершает job.
Нужен для проверки очереди, lease/heartbeat и сценариев сбоев без GPU.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path


class WorkerError(RuntimeError):
    pass


@dataclass(frozen=True)
class ClaimedJob:
    job_id: str
    attempt_id: str
    kind: str
    inputs: dict[str, object]
    output_prefix: str


class WorkerClient:
    """Минимальный HTTP-клиент worker API на stdlib."""

    def __init__(self, base_url: str, token: str, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, object] | None = None,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> object | None:
        payload = data if data is not None else (
            json.dumps(body).encode("utf-8") if body is not None else None
        )
        request = urllib.request.Request(self.base_url + path, data=payload, method=method)
        request.add_header("Authorization", f"Bearer {self.token}")
        if body is not None:
            request.add_header("Content-Type", "application/json")
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise WorkerError(f"{method} {path} -> {error.code}: {detail}") from error
        except urllib.error.URLError as error:
            raise WorkerError(f"{method} {path} failed: {error.reason}") from error
        return json.loads(raw) if raw else None

    def claim(
        self, worker_name: str, *, lease_seconds: int = 60, kinds: list[str] | None = None
    ) -> ClaimedJob | None:
        body = {
            "worker_name": worker_name,
            "kinds": kinds or ["render_video"],
            "lease_seconds": lease_seconds,
        }
        result = self._request("POST", "/api/worker/claim", body=body)
        if result is None:
            return None
        return ClaimedJob(
            job_id=str(result["job_id"]),
            attempt_id=str(result["attempt_id"]),
            kind=str(result["kind"]),
            inputs=dict(result.get("inputs") or {}),
            output_prefix=str(result.get("output_prefix") or ""),
        )

    def heartbeat(
        self,
        job_id: str,
        worker_name: str,
        *,
        progress: float | None = None,
        stage: str | None = None,
        lease_seconds: int = 60,
    ) -> dict[str, object]:
        result = self._request(
            "POST",
            f"/api/worker/jobs/{job_id}/heartbeat",
            body={
                "worker_name": worker_name,
                "progress": progress,
                "stage": stage,
                "lease_seconds": lease_seconds,
            },
        )
        return dict(result or {})

    def upload_artifact(
        self,
        job_id: str,
        worker_name: str,
        kind: str,
        source: Path,
        mime_type: str,
    ) -> dict[str, object]:
        data = source.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        query = urllib.parse.urlencode({"worker_name": worker_name, "kind": kind})
        result = self._request(
            "POST",
            f"/api/worker/jobs/{job_id}/artifacts?{query}",
            data=data,
            headers={"X-Content-SHA256": digest, "Content-Type": mime_type},
        )
        return dict(result or {})

    def complete(
        self,
        job_id: str,
        worker_name: str,
        *,
        duration_s: float | None = None,
        native_fps: float | None = None,
        workflow_version: str | None = None,
        model_hash: str | None = None,
        seed: int | None = None,
    ) -> dict[str, object]:
        result = self._request(
            "POST",
            f"/api/worker/jobs/{job_id}/complete",
            body={
                "worker_name": worker_name,
                "duration_s": duration_s,
                "native_fps": native_fps,
                "workflow_version": workflow_version,
                "model_hash": model_hash,
                "seed": seed,
            },
        )
        return dict(result or {})

    def fail(
        self,
        job_id: str,
        worker_name: str,
        error_code: str,
        *,
        retryable: bool = False,
        message: str | None = None,
    ) -> dict[str, object]:
        result = self._request(
            "POST",
            f"/api/worker/jobs/{job_id}/fail",
            body={
                "worker_name": worker_name,
                "error_code": error_code,
                "retryable": retryable,
                "message": message,
            },
        )
        return dict(result or {})

    def resume(self, worker_name: str) -> dict[str, object]:
        result = self._request(
            "POST", "/api/worker/resume", body={"worker_name": worker_name}
        )
        return dict(result or {})

    def download(self, content_url: str, destination: Path) -> str:
        request = urllib.request.Request(self.base_url + content_url)
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            data = response.read()
        destination.write_bytes(data)
        return hashlib.sha256(data).hexdigest()


def build_ffmpeg_command(
    destination: Path,
    *,
    frames: int = 24,
    fps: int = 12,
    size: str = "320x240",
    color: str = "0x3355aa",
) -> list[str]:
    duration = max(frames, 1) / max(fps, 1)
    return [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"color=c={color}:s={size}:d={duration:.3f}:r={fps}",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(destination),
    ]


def generate_mp4(
    destination: Path,
    *,
    frames: int = 24,
    fps: int = 12,
    size: str = "320x240",
    ffmpeg: str = "ffmpeg",
) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = build_ffmpeg_command(destination, frames=frames, fps=fps, size=size)
    command[0] = ffmpeg
    try:
        subprocess.run(command, check=True, capture_output=True)
    except subprocess.CalledProcessError as error:
        raise WorkerError(
            f"ffmpeg failed: {error.stderr.decode('utf-8', errors='replace')}"
        ) from error
    return destination


def probe_duration(path: Path, *, ffprobe: str = "ffprobe") -> tuple[float, bool]:
    """Локальная проверка результата перед отправкой (ffprobe)."""

    command = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=codec_type",
        "-of",
        "json",
        str(path),
    ]
    completed = subprocess.run(command, check=True, capture_output=True)
    payload = json.loads(completed.stdout or b"{}")
    duration = float(payload.get("format", {}).get("duration") or 0.0)
    has_video = any(
        stream.get("codec_type") == "video" for stream in payload.get("streams", [])
    )
    return duration, has_video


def process_one(
    client: WorkerClient,
    job: ClaimedJob,
    worker_name: str,
    *,
    force_fail: str | None = None,
    delay: float = 0.0,
    frames: int = 24,
    fps: int = 12,
    ffmpeg: str = "ffmpeg",
) -> dict[str, object]:
    """Обрабатывает один job; возвращает ответ complete/fail."""

    if delay:
        time.sleep(delay)
    start_image = job.inputs.get("start_image") or {}
    expected_sha = start_image.get("sha256") if isinstance(start_image, dict) else None
    content_url = start_image.get("content_url") if isinstance(start_image, dict) else None

    with tempfile.TemporaryDirectory(prefix="fake-worker-") as directory:
        workdir = Path(directory)
        if content_url and isinstance(content_url, str):
            start_path = workdir / "start.png"
            actual_sha = client.download(content_url, start_path)
            if expected_sha and actual_sha != expected_sha:
                return client.fail(
                    job.job_id,
                    worker_name,
                    "start_image_sha256_mismatch",
                    retryable=False,
                    message=f"expected {expected_sha}, actual {actual_sha}",
                )
            client.heartbeat(job.job_id, worker_name, progress=0.2, stage="prepare")

        if force_fail:
            return client.fail(job.job_id, worker_name, force_fail, retryable=False)

        client.heartbeat(job.job_id, worker_name, progress=0.6, stage="sampling")
        output = generate_mp4(workdir / "output.mp4", frames=frames, fps=fps, ffmpeg=ffmpeg)
        duration, has_video = probe_duration(output)
        if not has_video or duration <= 0:
            return client.fail(
                job.job_id, worker_name, "invalid_output", retryable=True
            )

        client.heartbeat(job.job_id, worker_name, progress=0.9, stage="upload")
        artifact = client.upload_artifact(
            job.job_id, worker_name, "video", output, "video/mp4"
        )
        return client.complete(
            job.job_id,
            worker_name,
            duration_s=duration,
            native_fps=float(fps),
            workflow_version="fake-v1",
            model_hash="fake",
            seed=0,
        ) | {"artifact_id": artifact.get("id")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FakeWorker Mary Studio (WP-06)")
    parser.add_argument("--url", default=os.environ.get("MARY_API_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--token", default=os.environ.get("MARY_WORKER_TOKEN", ""))
    parser.add_argument("--name", default=os.environ.get("MARY_WORKER_NAME", "fake-1"))
    parser.add_argument("--once", action="store_true", help="обработать не более одной job")
    parser.add_argument("--delay", type=float, default=0.0)
    parser.add_argument("--fail", dest="fail_code", default=None)
    parser.add_argument(
        "--crash-after-claim",
        action="store_true",
        help="выйти сразу после claim (имитация kill -9)",
    )
    parser.add_argument("--poll", type=float, default=2.0)
    args = parser.parse_args(argv)

    if not args.token:
        parser.error("worker token is required (--token or MARY_WORKER_TOKEN)")

    client = WorkerClient(args.url, args.token)
    processed = 0
    while True:
        job = client.claim(args.name)
        if job is None:
            if args.once:
                return 0
            time.sleep(args.poll)
            continue
        if args.crash_after_claim:
            print(f"claimed {job.job_id}, crashing", file=sys.stderr)
            return 137
        result = process_one(
            client,
            job,
            args.name,
            force_fail=args.fail_code,
            delay=args.delay,
        )
        print(json.dumps(result, indent=2))
        processed += 1
        if args.once:
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
