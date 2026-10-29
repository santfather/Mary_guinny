"""Реальный LTX-воркер: Mary Studio job → ComfyUI LTX-2.3 MLX → artifact (WP-N3).

Воркер забирает одну `render_video` job через существующий worker API, скачивает
утверждённый стартовый кадр, собирает payload шота через
`pipeline/comfyui/ltx_adapter.py`, запускает его в ComfyUI, продлевает lease
heartbeat-ами во время рендера, проверяет MP4 через ffprobe и загружает результат.

Никаких миграций, новых эндпоинтов и прямых записей в БД: только протокол
`/api/worker/*` (WP-06). Один процесс обрабатывает одну тяжёлую job за раз.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import httpx  # noqa: E402

from client import ClaimedJob, WorkerClient, WorkerError, probe_duration  # noqa: E402
from pipeline.comfyui import ltx_adapter  # noqa: E402
from pipeline.comfyui.client import ComfyUIClient  # noqa: E402

DEFAULT_WORKFLOW = REPO_ROOT / "comfyui-workflows" / "ltx23_mlx_q4_i2v.api.json"
DEFAULT_COMFY_URL = "http://127.0.0.1:8188"
COMFY_SUBFOLDER = "mary_guiness"


class RenderError(RuntimeError):
    """Ошибка рендера с кодом для `POST /api/worker/jobs/{id}/fail`."""

    def __init__(
        self, error_code: str, message: str | None = None, *, retryable: bool = False
    ) -> None:
        super().__init__(message or error_code)
        self.error_code = error_code
        self.retryable = retryable


@dataclass(frozen=True)
class RenderSettings:
    comfy_url: str = DEFAULT_COMFY_URL
    workflow_path: Path = DEFAULT_WORKFLOW
    aspect_ratio: str = "9:16"
    long_side: int = ltx_adapter.DEFAULT_LONG_SIDE
    cfg_scale: float = ltx_adapter.DEFAULT_CFG_SCALE
    poll_interval: float = 5.0
    render_timeout_s: float = 3600.0
    lease_seconds: int = 300


def render_seed(attempt_id: str, seed: object) -> int:
    """seed из job, иначе детерминированный: повтор даёт тот же результат."""

    if isinstance(seed, int) and not isinstance(seed, bool) and seed >= 0:
        return seed
    digest = hashlib.sha256(attempt_id.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 2**31


def process_one(
    api: WorkerClient,
    job: ClaimedJob,
    worker_name: str,
    settings: RenderSettings | None = None,
    *,
    comfy: ComfyUIClient | None = None,
) -> dict[str, object]:
    """Обрабатывает один job; возвращает ответ complete/fail."""

    settings = settings or RenderSettings()
    try:
        return _render(
            api, job, worker_name, settings, comfy or _comfy_client(settings)
        )
    except RenderError as error:
        return api.fail(
            job.job_id,
            worker_name,
            error.error_code,
            retryable=error.retryable,
            message=str(error),
        )


def _render(
    api: WorkerClient,
    job: ClaimedJob,
    worker_name: str,
    settings: RenderSettings,
    comfy: ComfyUIClient,
) -> dict[str, object]:
    inputs = job.inputs
    prompt = str(inputs.get("prompt") or "").strip()
    if not prompt:
        raise RenderError("missing_prompt", "у job нет motion-промпта")
    frames = int(inputs.get("frames") or 0)
    if frames <= 0:
        raise RenderError("missing_frames", "у job нет target_duration_frames")
    fps = int(float(inputs.get("fps") or 0))
    if fps <= 0:
        raise RenderError("missing_fps", "у job нет timeline_fps")

    start = _start_image(inputs)
    shot_key = str(inputs.get("shot_key") or f"job-{job.job_id[:8]}")
    seed = render_seed(job.attempt_id, inputs.get("seed"))

    try:
        template = ltx_adapter.load_template(settings.workflow_path)
        binding = ltx_adapter.build_shot_binding(
            shot_key=shot_key,
            prompt=prompt,
            image_name="start.png",
            seed=seed,
            attempt_id=job.attempt_id,
            aspect_ratio=settings.aspect_ratio,
            seconds=frames / fps,
            fps=fps,
            cfg_scale=settings.cfg_scale,
            long_side=settings.long_side,
        )
    except (OSError, ValueError) as error:
        raise RenderError("invalid_workflow", str(error)) from error
    if binding.num_frames != frames:
        raise RenderError(
            "frames_not_supported",
            f"LTX принимает {binding.num_frames} кадров вместо {frames}",
        )

    with tempfile.TemporaryDirectory(prefix="ltx-worker-") as directory:
        workdir = Path(directory)
        start_path = workdir / "start.png"
        actual_sha = api.download(start["content_url"], start_path)
        if actual_sha != start["sha256"]:
            raise RenderError(
                "start_image_sha256_mismatch",
                f"expected {start['sha256']}, actual {actual_sha}",
            )
        _beat(api, job, worker_name, settings, 0.05, "prepare")

        polls = {"count": 0}

        def on_poll() -> None:
            # Lease продлевается на каждом опросе: иначе долгий рендер
            # превратится в `lease_expired` и job потеряется.
            polls["count"] += 1
            _beat(
                api,
                job,
                worker_name,
                settings,
                min(0.9, 0.2 + polls["count"] * 0.02),
                "sampling",
            )

        try:
            workflow_version, workflow, history = asyncio.run(
                _run_comfy(comfy, template, binding, start_path, settings, on_poll)
            )
            video_path = workdir / "output.mp4"
            _save_video(comfy, history, video_path)
        except RenderError:
            raise
        except (httpx.HTTPError, TimeoutError, OSError) as error:
            raise RenderError("comfy_error", str(error), retryable=True) from error

        try:
            duration, has_video = probe_duration(video_path)
        except (OSError, subprocess.SubprocessError, ValueError) as error:
            raise RenderError("probe_failed", str(error)) from error
        if not has_video or duration <= 0:
            raise RenderError("invalid_output", "ffprobe: нет видео-дорожки", retryable=True)

        _beat(api, job, worker_name, settings, 0.95, "upload")
        artifact = api.upload_artifact(
            job.job_id, worker_name, "video", video_path, "video/mp4"
        )
        return api.complete(
            job.job_id,
            worker_name,
            duration_s=duration,
            native_fps=binding.frame_rate,
            workflow_version=workflow_version,
            model_hash=ltx_adapter.model_id(template),
            seed=seed,
            parameters={
                **binding.as_parameters(),
                "aspect_ratio": settings.aspect_ratio,
                "long_side": settings.long_side,
                "workflow_snapshot": workflow,
            },
        ) | {"artifact_id": artifact.get("id")}


async def _run_comfy(
    comfy: ComfyUIClient,
    template: dict[str, Any],
    binding: ltx_adapter.ShotBinding,
    start_path: Path,
    settings: RenderSettings,
    on_poll: Callable[[], None],
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """Загружает кадр, ставит prompt и ждёт историю, продлевая lease.

    Возвращает версию workflow, связанный workflow (snapshot для provenance)
    и историю ComfyUI.
    """

    if not await comfy.is_available():
        raise RenderError(
            "comfy_unavailable", f"ComfyUI недоступен: {settings.comfy_url}", retryable=True
        )
    uploaded = await comfy.upload_image(start_path, subfolder=COMFY_SUBFOLDER)
    subfolder = uploaded.get("subfolder") or ""
    image_ref = f"{subfolder}/{uploaded['name']}" if subfolder else uploaded["name"]
    try:
        workflow = ltx_adapter.bind_workflow(
            template, replace(binding, image_name=image_ref)
        )
    except ltx_adapter.BindingError as error:
        raise RenderError("invalid_workflow", str(error)) from error

    prompt_id = await comfy.queue_prompt(workflow)
    history = await comfy.wait_for_prompt(
        prompt_id,
        settings.poll_interval,
        timeout=settings.render_timeout_s,
        on_poll=on_poll,
    )
    _raise_on_comfy_error(history)
    return ltx_adapter.workflow_version(template), workflow, history


def _save_video(
    comfy: ComfyUIClient, history: dict[str, Any], destination: Path
) -> None:
    images = comfy.extract_saved_images(history)
    if not images:
        raise RenderError("comfy_no_output", "ComfyUI не вернул видео", retryable=True)
    first = images[0]
    data = asyncio.run(
        comfy.get_image(first["filename"], first["subfolder"], first["type"])
    )
    if not data:
        raise RenderError("comfy_no_output", "пустой ответ /view", retryable=True)
    destination.write_bytes(data)


def _raise_on_comfy_error(history: dict[str, Any]) -> None:
    status = history.get("status")
    if not isinstance(status, dict) or status.get("status_str") != "error":
        return
    detail = json.dumps(status.get("messages"), ensure_ascii=False)
    raise RenderError("comfy_error", detail[:500] or "ComfyUI execution error", retryable=True)


def _start_image(inputs: dict[str, object]) -> dict[str, str]:
    start = inputs.get("start_image")
    if not isinstance(start, dict):
        raise RenderError("missing_start_image", "у job нет стартового кадра")
    content_url = start.get("content_url")
    digest = start.get("sha256")
    if not isinstance(content_url, str) or not isinstance(digest, str):
        raise RenderError("missing_start_image", "start_image без content_url/sha256")
    return {"content_url": content_url, "sha256": digest}


def _beat(
    api: WorkerClient,
    job: ClaimedJob,
    worker_name: str,
    settings: RenderSettings,
    progress: float,
    stage: str,
) -> None:
    api.heartbeat(
        job.job_id,
        worker_name,
        progress=progress,
        stage=stage,
        lease_seconds=settings.lease_seconds,
    )


def _comfy_client(settings: RenderSettings) -> ComfyUIClient:
    return ComfyUIClient(settings.comfy_url, timeout=settings.render_timeout_s)


def _process_job(
    api: WorkerClient, job: ClaimedJob, args: argparse.Namespace, settings: RenderSettings
) -> int:
    """Обрабатывает одну job; возвращает 0 или 1 для `--once`."""

    try:
        result = process_one(api, job, args.name, settings)
    except WorkerError as error:
        # Потеря lease/сети: ComfyUI продолжает считать, отмены пока нет.
        print(
            f"job {job.job_id}: {error} (рендер в ComfyUI не отменяется)",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, indent=2))
    return 0


def _job_loop(
    api: WorkerClient, args: argparse.Namespace, settings: RenderSettings
) -> int:
    """Обычный режим: воркер берёт любую готовую `render_video` job."""

    while True:
        try:
            job = api.claim(args.name, lease_seconds=args.lease)
        except WorkerError as error:
            print(f"claim failed: {error}", file=sys.stderr)
            time.sleep(args.poll)
            continue
        if job is None:
            if args.once:
                return 0
            time.sleep(args.poll)
            continue
        code = _process_job(api, job, args, settings)
        if args.once:
            return code


def _series_loop(
    api: WorkerClient, args: argparse.Namespace, settings: RenderSettings
) -> int:
    """Последовательный прогон серии (WP-N4): одна тяжёлая job за раз.

    Сервер (`POST /api/worker/series/next`) двигает item'ы, поэтому порядок,
    пауза и `stop_after_current` соблюдаются без отдельной очереди.
    """

    while True:
        try:
            reply = api.series_next(args.name, run_id=args.series_run)
        except WorkerError as error:
            print(f"series/next failed: {error}", file=sys.stderr)
            time.sleep(args.poll)
            continue

        reply_status = str(reply.get("status") or "")
        if reply_status in ("idle", "completed", "cancelled", "failed", "paused"):
            print(json.dumps(reply, indent=2))
            return 0
        if reply_status in ("running", "busy"):
            time.sleep(args.poll)
            continue
        if reply_status == "skipped":
            print(json.dumps(reply, indent=2))
            continue
        if reply_status != "queued":
            print(f"series/next: неизвестный статус {reply_status}", file=sys.stderr)
            return 1

        try:
            job = api.claim(args.name, lease_seconds=args.lease)
        except WorkerError as error:
            print(f"claim failed: {error}", file=sys.stderr)
            time.sleep(args.poll)
            continue
        if job is None:
            time.sleep(args.poll)
            continue
        if job.job_id != reply.get("job_id"):
            # Серия создаёт ровно одну job, поэтому это чужая job из очереди.
            print(
                f"warning: claim вернул {job.job_id}, серия ждала"
                f" {reply.get('job_id')}; обрабатываем полученную",
                file=sys.stderr,
            )

        code = _process_job(api, job, args, settings)
        if code != 0 and args.once:
            return code
        if args.once:
            return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LTX-воркер Mary Studio (WP-N3/N4)")
    parser.add_argument("--url", default=os.environ.get("MARY_API_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--token", default=os.environ.get("MARY_WORKER_TOKEN", ""))
    parser.add_argument("--name", default=os.environ.get("MARY_WORKER_NAME", "ltx-1"))
    parser.add_argument("--once", action="store_true", help="обработать не более одной job")
    parser.add_argument("--poll", type=float, default=2.0, help="пауза между claim")
    parser.add_argument(
        "--series",
        action="store_true",
        help="работать по активному прогону серии (WP-N4)",
    )
    parser.add_argument(
        "--series-run",
        default=None,
        help="id прогона серии; включает режим серии так же, как --series",
    )
    parser.add_argument(
        "--comfy-url", default=os.environ.get("MARY_COMFY_URL", DEFAULT_COMFY_URL)
    )
    parser.add_argument("--workflow", default=str(DEFAULT_WORKFLOW))
    parser.add_argument("--aspect-ratio", default="9:16")
    parser.add_argument("--long-side", type=int, default=ltx_adapter.DEFAULT_LONG_SIDE)
    parser.add_argument("--cfg-scale", type=float, default=ltx_adapter.DEFAULT_CFG_SCALE)
    parser.add_argument("--comfy-poll", type=float, default=5.0)
    parser.add_argument("--timeout", type=float, default=3600.0)
    parser.add_argument("--lease", type=int, default=300)
    args = parser.parse_args(argv)

    if not args.token:
        parser.error("worker token is required (--token or MARY_WORKER_TOKEN)")

    settings = RenderSettings(
        comfy_url=args.comfy_url,
        workflow_path=Path(args.workflow),
        aspect_ratio=args.aspect_ratio,
        long_side=args.long_side,
        cfg_scale=args.cfg_scale,
        poll_interval=args.comfy_poll,
        render_timeout_s=args.timeout,
        lease_seconds=args.lease,
    )
    api = WorkerClient(args.url, args.token)
    if args.series or args.series_run:
        return _series_loop(api, args, settings)
    return _job_loop(api, args, settings)


if __name__ == "__main__":
    raise SystemExit(main())
