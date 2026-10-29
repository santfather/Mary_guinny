"""FakeWorker — реализация worker-протокола без ComfyUI (WP-06).

Тянет job через `POST /api/worker/claim`, скачивает стартовый кадр, генерирует
короткий валидный MP4 через ffmpeg, загружает артефакт и завершает job.
Нужен для проверки очереди, lease/heartbeat и сценариев сбоев без GPU.

HTTP-клиент протокола и `probe_duration` живут в `worker/client.py` (WP-N3),
чтобы реальный `ltx_worker.py` не дублировал контракт.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from client import ClaimedJob, WorkerClient, WorkerError, probe_duration

__all__ = [
    "ClaimedJob",
    "WorkerClient",
    "WorkerError",
    "probe_duration",
    "build_ffmpeg_command",
    "generate_mp4",
    "process_one",
    "main",
]


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
