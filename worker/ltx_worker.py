"""Реальный LTX-воркер: Mary Studio job → ComfyUI LTX-2.3 MLX → artifact (WP-N3/N4/M4).

Воркер забирает одну `render_video` job через существующий worker API, скачивает
утверждённый стартовый кадр, собирает payload шота через
`pipeline/comfyui/ltx_adapter.py`, запускает его в ComfyUI, продлевает lease
heartbeat-ами во время рендера, проверяет MP4 через ffprobe и загружает результат.

WP-M4: сразу после `/prompt` воркер пишет `prompt_id` в локальный state-файл и
сообщает его серверу (`POST /api/worker/jobs/{id}/external`). После рестарта
`resume` + `/history/{prompt_id}` позволяют забрать готовый рендер без повторного
запуска; если ComfyUI prompt не знает — job проваливается с retryable-кодом.

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
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
BACKEND_DIR = REPO_ROOT / "backend"
if BACKEND_DIR.is_dir() and str(BACKEND_DIR) not in sys.path:
    # `app.notify` — stdlib-only модуль баннеров macOS; других импортов backend нет.
    sys.path.append(str(BACKEND_DIR))

import httpx  # noqa: E402

from app.notify import notify  # noqa: E402
from client import ClaimedJob, WorkerClient, WorkerError, probe_duration  # noqa: E402
from pipeline.comfyui import ltx_adapter  # noqa: E402
from pipeline.comfyui.client import ComfyUIClient  # noqa: E402
from thermal import (  # noqa: E402
    DEFAULT_HELPER,
    DEFAULT_LOG_FILE,
    DEFAULT_STATE_FILE as DEFAULT_THERMAL_STATE,
    PROFILE_NAMES,
    KeepAwake,
    NullGate,
    Probes,
    ThermalGate,
    build_helper,
)

DEFAULT_WORKFLOW = REPO_ROOT / "comfyui-workflows" / "ltx23_mlx_q4_i2v.api.json"
DEFAULT_COMFY_URL = "http://127.0.0.1:8188"
DEFAULT_STATE_FILE = Path.home() / ".mary-studio" / "ltx-worker-state.json"
COMFY_SUBFOLDER = "mary_guiness"
THERMAL_OFF = NullGate()


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
    # WP-M7: имя пресета и источник значений (`cli`/`api`/`default`) — в провенанс.
    preset: str | None = None
    preset_source: str = "default"
    # WP-THERMAL-03: политика допуска задаётся профилем; здесь она фиксируется,
    # чтобы рендер и thermal-гейт не расходились.
    thermal_profile: str = "balanced"
    # default_factory, а не значение: путь разрешается при создании настроек.
    state_path: Path = field(default_factory=lambda: DEFAULT_STATE_FILE)


DEFAULT_ASPECT_RATIO = "9:16"


@dataclass(frozen=True)
class PresetChoice:
    preset: str | None
    source: str
    aspect_ratio: str
    long_side: int
    cfg_scale: float
    warning: str | None = None


def resolve_preset(
    *,
    requested: str | None,
    aspect_ratio: str | None,
    long_side: int | None,
    cfg_scale: float | None,
    fetch: Callable[[], dict[str, object]] | None,
) -> PresetChoice:
    """WP-M7: явные флаги важнее рекомендации API; без API — встроенные значения."""

    if aspect_ratio is not None or long_side is not None or cfg_scale is not None:
        return PresetChoice(
            preset=requested,
            source="cli",
            aspect_ratio=aspect_ratio or DEFAULT_ASPECT_RATIO,
            long_side=long_side if long_side is not None else ltx_adapter.DEFAULT_LONG_SIDE,
            cfg_scale=cfg_scale
            if cfg_scale is not None
            else ltx_adapter.DEFAULT_CFG_SCALE,
        )

    fallback = PresetChoice(
        preset=None,
        source="default",
        aspect_ratio=DEFAULT_ASPECT_RATIO,
        long_side=ltx_adapter.DEFAULT_LONG_SIDE,
        cfg_scale=ltx_adapter.DEFAULT_CFG_SCALE,
    )
    if fetch is None:
        return fallback

    try:
        payload = fetch()
    except (WorkerError, OSError) as error:
        return replace(
            fallback, warning=f"пресет не получен ({error}); встроенные умолчания"
        )

    target = requested
    if target is None:
        recommended = payload.get("recommended")
        target = recommended if isinstance(recommended, str) and recommended else None
        if target is None:
            reason = payload.get("reason")
            return replace(
                fallback, warning=f"нет рекомендации пресета: {reason or 'причина не указана'}"
            )

    entries = payload.get("presets")
    entry = next(
        (
            item
            for item in (entries if isinstance(entries, list) else [])
            if isinstance(item, dict) and item.get("name") == target
        ),
        None,
    )
    if entry is None:
        return replace(fallback, warning=f"пресет {target} отсутствует в ответе API")

    try:
        resolved = PresetChoice(
            preset=target,
            source="api" if requested is None else "cli",
            aspect_ratio=str(entry.get("aspect_ratio") or DEFAULT_ASPECT_RATIO),
            long_side=int(entry["long_side"]),
            cfg_scale=float(entry["cfg_scale"]),
        )
    except (KeyError, TypeError, ValueError):
        return replace(fallback, warning=f"некорректный пресет {target} в ответе API")
    return resolved


def _load_state(path: Path) -> dict[str, dict[str, Any]]:
    try:
        payload = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        str(key): value for key, value in payload.items() if isinstance(value, dict)
    }


def _write_state(path: Path, state: dict[str, dict[str, Any]]) -> None:
    """Пишет state атомарно: падение воркера не оставит обрезанный JSON."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), "utf-8")
    os.replace(temporary, path)


def _remember_prompt(path: Path, job_id: str, entry: dict[str, Any]) -> None:
    """Пишет prompt_id в state best-effort: рендер уже поставлен в ComfyUI.

    Источник истины — `jobs.external_id` на сервере; недоступный `~/.mary-studio`
    не должен превращать живой рендер в `fail`.
    """

    state = _load_state(path)
    state[job_id] = entry
    try:
        _write_state(path, state)
    except OSError as error:
        print(f"warning: не удалось записать {path}: {error}", file=sys.stderr)


def _forget_prompt(path: Path, job_id: str) -> None:
    state = _load_state(path)
    if state.pop(job_id, None) is None:
        return
    try:
        _write_state(path, state)
    except OSError as error:
        print(f"warning: не удалось обновить {path}: {error}", file=sys.stderr)


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
    gate: ThermalGate | NullGate | None = None,
) -> dict[str, object]:
    """Обрабатывает один job; возвращает ответ complete/fail."""

    settings = settings or RenderSettings()
    try:
        return _render(
            api,
            job,
            worker_name,
            settings,
            comfy or _comfy_client(settings),
            gate or THERMAL_OFF,
        )
    except RenderError as error:
        result = api.fail(
            job.job_id,
            worker_name,
            error.error_code,
            retryable=error.retryable,
            message=str(error),
        )
        # Если `fail` не дошёл до сервера, запись остаётся: следующий старт
        # попробует забрать рендер через `/history`.
        _forget_prompt(settings.state_path, job.job_id)
        return result


def _render(
    api: WorkerClient,
    job: ClaimedJob,
    worker_name: str,
    settings: RenderSettings,
    comfy: ComfyUIClient,
    gate: ThermalGate | NullGate,
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

    workflow_version = ltx_adapter.workflow_version(template)
    model_hash = ltx_adapter.model_id(template)
    # WP-THERMAL-02: условия допуска на момент старта — в провенанс попытки.
    telemetry = gate.job_telemetry()
    render_started = time.monotonic()
    parameters: dict[str, object] = {
        **binding.as_parameters(),
        "aspect_ratio": settings.aspect_ratio,
        "long_side": settings.long_side,
        # WP-M7: явно фиксируем, какой пресет и откуда применён.
        "preset": settings.preset,
        "preset_source": settings.preset_source,
    }
    # WP-THERMAL-03 (T-07): preview — отдельная попытка, а не замена production.
    if inputs.get("preview"):
        parameters["preview"] = True
    if telemetry:
        parameters["thermal"] = dict(telemetry)

    def on_prompt(prompt_id: str, workflow: dict[str, Any]) -> None:
        """WP-M4: prompt_id фиксируется локально и на сервере до ожидания."""

        _remember_prompt(
            settings.state_path,
            job.job_id,
            {
                "prompt_id": prompt_id,
                "attempt_id": job.attempt_id,
                "native_fps": binding.frame_rate,
                "workflow_version": workflow_version,
                "model_hash": model_hash,
                "seed": seed,
                "parameters": {**parameters, "workflow_snapshot": workflow},
            },
        )
        try:
            api.link_external(job.job_id, worker_name, prompt_id)
        except WorkerError as error:
            # Сервер не узнал prompt_id — рендер всё равно продолжится, а при
            # рестарте поможет state-файл (если запись удалась).
            print(
                f"warning: не удалось связать prompt {prompt_id}: {error}",
                file=sys.stderr,
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
            gate.touch(job_id=job.job_id)
            gate.sample(telemetry)
            _beat(
                api,
                job,
                worker_name,
                settings,
                min(0.9, 0.2 + polls["count"] * 0.02),
                "sampling",
            )

        try:
            _, workflow, history = asyncio.run(
                _run_comfy(
                    comfy, template, binding, start_path, settings, on_poll, on_prompt
                )
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
        final_parameters = {**parameters, "workflow_snapshot": workflow}
        peak_mem_mb: int | None = None
        if telemetry:
            final_parameters["thermal"] = {
                **telemetry,
                "render_seconds": round(time.monotonic() - render_started, 3),
            }
            peak = telemetry.get("peak_mem_mb")
            peak_mem_mb = peak if isinstance(peak, int) else None
        result = api.complete(
            job.job_id,
            worker_name,
            duration_s=duration,
            native_fps=binding.frame_rate,
            workflow_version=workflow_version,
            model_hash=model_hash,
            seed=seed,
            parameters=final_parameters,
            peak_mem_mb=peak_mem_mb,
        )
        _forget_prompt(settings.state_path, job.job_id)
        return result | {"artifact_id": artifact.get("id")}


def recover(
    api: WorkerClient,
    worker_name: str,
    settings: RenderSettings | None = None,
    *,
    comfy: ComfyUIClient | None = None,
) -> list[dict[str, object]]:
    """Забирает рендеры, поставленные в ComfyUI до рестарта (WP-M4).

    `resume` отдаёт job'ы, lease которых принадлежит этому воркеру, вместе с
    `external_id`; локальный state-файл добавляет данные для `complete`.
    Если `/history` не знает prompt, job уходит в `retry_wait`
    (`external_prompt_lost`) и рендерится заново штатным путём.
    """

    settings = settings or RenderSettings()
    comfy = comfy or _comfy_client(settings)
    reply = api.resume(worker_name)
    jobs = [item for item in reply.get("jobs") or [] if isinstance(item, dict)]
    state = _load_state(settings.state_path)
    # Записи о job'ах, которые сервер уже не считает нашими, бесполезны.
    for stale in set(state) - {str(job.get("job_id")) for job in jobs}:
        _forget_prompt(settings.state_path, stale)

    results: list[dict[str, object]] = []
    for job in jobs:
        job_id = str(job.get("job_id") or "")
        if not job_id:
            continue
        entry = state.get(job_id) or {}
        prompt_id = job.get("external_id") or entry.get("prompt_id")
        if not prompt_id:
            # Job взят, но до `/prompt` не дошёл: завершать нечего.
            continue
        results.append(
            _recover_job(api, job_id, worker_name, str(prompt_id), entry, settings, comfy)
        )
    return results


def _recover_job(
    api: WorkerClient,
    job_id: str,
    worker_name: str,
    prompt_id: str,
    entry: dict[str, Any],
    settings: RenderSettings,
    comfy: ComfyUIClient,
) -> dict[str, object]:
    try:
        return _finish_recovered(
            api, job_id, worker_name, prompt_id, entry, settings, comfy
        )
    except RenderError as error:
        result = api.fail(
            job_id,
            worker_name,
            error.error_code,
            retryable=error.retryable,
            message=str(error),
        )
        _forget_prompt(settings.state_path, job_id)
        return result


async def _await_history(
    comfy: ComfyUIClient,
    prompt_id: str,
    settings: RenderSettings,
    on_poll: Callable[[], None],
) -> dict[str, Any]:
    """История завершённого prompt'а либо ожидание ещё выполняющегося.

    Отсутствие в `/history` само по себе ничего не значит: после рестарта
    воркера ComfyUI обычно продолжает рендер. `external_prompt_lost` — только
    если prompt'а нет и в `/queue`. Проверка повторяется на каждом опросе:
    prompt может исчезнуть из очереди, так и не попав в историю (очистка
    очереди, падение ComfyUI).
    """

    deadline = time.monotonic() + settings.render_timeout_s
    while True:
        history = await comfy.get_history(prompt_id)
        if history is not None:
            return history
        if not await comfy.is_queued(prompt_id):
            # History пишется чуть позже снятия из очереди: сверяемся ещё раз.
            history = await comfy.get_history(prompt_id)
            if history is not None:
                return history
            raise RenderError(
                "external_prompt_lost",
                f"ComfyUI не знает prompt {prompt_id}",
                retryable=True,
            )
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"ComfyUI не завершил prompt {prompt_id} за {settings.render_timeout_s}s"
            )
        on_poll()
        await asyncio.sleep(settings.poll_interval)


def _finish_recovered(
    api: WorkerClient,
    job_id: str,
    worker_name: str,
    prompt_id: str,
    entry: dict[str, Any],
    settings: RenderSettings,
    comfy: ComfyUIClient,
) -> dict[str, object]:
    def on_poll() -> None:
        # Пока воркер лежал, lease мог истечь: heartbeat забирает job обратно.
        api.heartbeat(
            job_id,
            worker_name,
            progress=0.9,
            stage="recover",
            lease_seconds=settings.lease_seconds,
        )

    on_poll()
    try:
        history = asyncio.run(_await_history(comfy, prompt_id, settings, on_poll))
    except (httpx.HTTPError, TimeoutError, OSError) as error:
        raise RenderError("comfy_error", str(error), retryable=True) from error
    _raise_on_comfy_error(history)

    with tempfile.TemporaryDirectory(prefix="ltx-recover-") as directory:
        video_path = Path(directory) / "output.mp4"
        _save_video(comfy, history, video_path)
        try:
            duration, has_video = probe_duration(video_path)
        except (OSError, subprocess.SubprocessError, ValueError) as error:
            raise RenderError("probe_failed", str(error)) from error
        if not has_video or duration <= 0:
            raise RenderError("invalid_output", "ffprobe: нет видео-дорожки", retryable=True)
        artifact = api.upload_artifact(
            job_id, worker_name, "video", video_path, "video/mp4"
        )

    parameters = dict(entry.get("parameters") or {})
    parameters.update({"recovered": True, "prompt_id": prompt_id})
    result = api.complete(
        job_id,
        worker_name,
        duration_s=duration,
        native_fps=entry.get("native_fps"),
        workflow_version=entry.get("workflow_version"),
        model_hash=entry.get("model_hash"),
        seed=entry.get("seed"),
        parameters=parameters,
    )
    _forget_prompt(settings.state_path, job_id)
    return result | {"artifact_id": artifact.get("id"), "recovered": True}


async def _run_comfy(
    comfy: ComfyUIClient,
    template: dict[str, Any],
    binding: ltx_adapter.ShotBinding,
    start_path: Path,
    settings: RenderSettings,
    on_poll: Callable[[], None],
    on_prompt: Callable[[str, dict[str, Any]], None],
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """Загружает кадр, ставит prompt и ждёт историю, продлевая lease.

    `on_prompt` получает `prompt_id` и связанный workflow сразу после `/prompt`:
    так id попадает в state-файл и на сервер до начала долгого ожидания.
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
    on_prompt(prompt_id, workflow)
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


def _recover_at_startup(
    api: WorkerClient, args: argparse.Namespace, settings: RenderSettings
) -> None:
    """Завершает рендеры, пережившие рестарт воркера (WP-M4)."""

    try:
        with KeepAwake(enabled=getattr(args, "caffeinate", False)):
            results = recover(api, args.name, settings)
    except WorkerError as error:
        print(f"resume failed: {error}", file=sys.stderr)
        return
    for result in results:
        print(json.dumps(result, indent=2))


def _process_job(
    api: WorkerClient,
    job: ClaimedJob,
    args: argparse.Namespace,
    settings: RenderSettings,
    gate: ThermalGate | NullGate | None = None,
) -> int:
    """Обрабатывает одну job; возвращает 0 или 1 для `--once`."""

    gate = gate or THERMAL_OFF
    gate.start_job(job.job_id)
    completed = False
    awake = KeepAwake(enabled=getattr(args, "caffeinate", False))
    awake.start()
    try:
        try:
            result = process_one(api, job, args.name, settings, gate=gate)
            completed = result.get("status") == "completed"
        except WorkerError as error:
            # Потеря lease/сети: ComfyUI продолжает считать, отмены пока нет.
            print(
                f"job {job.job_id}: {error} (рендер в ComfyUI не отменяется)",
                file=sys.stderr,
            )
            return 1
    finally:
        awake.stop()
        # Партия и cooldown считаются по факту завершения попытки.
        gate.after_job(job_id=job.job_id, ok=completed)
    print(json.dumps(result, indent=2))
    return 0


def _wait_for_admission(
    gate: ThermalGate | NullGate,
    decision,
    args: argparse.Namespace,
    *,
    series: bool,
) -> bool:
    """Ожидание допуска. `True` — воркер должен остановиться без ошибки."""

    print(
        f"thermal: {decision.reason}; ждём {decision.wait_seconds:.0f} с",
        file=sys.stderr,
    )
    if gate.should_stop_waiting():
        reason = f"Термозащита ждёт слишком долго ({decision.reason})"
        notify(
            "Mary Studio: ожидание остановлено",
            reason + ("; прогон остаётся paused" if series else ""),
        )
        print(
            "thermal: превышено время ожидания — выхожу;"
            + (" прогон остаётся paused" if series else " job не взят"),
            file=sys.stderr,
        )
        return True
    if args.once:
        return True
    time.sleep(max(args.poll, decision.wait_seconds))
    return False


def _job_loop(
    api: WorkerClient,
    args: argparse.Namespace,
    settings: RenderSettings,
    gate: ThermalGate | NullGate | None = None,
) -> int:
    """Обычный режим: воркер берёт любую готовую `render_video` job."""

    gate = gate or THERMAL_OFF
    while True:
        # WP-THERMAL-02: допуск проверяется до claim, чтобы не держать lease.
        decision = gate.before_next()
        if not decision.allowed:
            if _wait_for_admission(gate, decision, args, series=False):
                return 1 if gate.should_stop_waiting() else 0
            continue
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
        code = _process_job(api, job, args, settings, gate)
        if args.once:
            return code


def _series_loop(
    api: WorkerClient,
    args: argparse.Namespace,
    settings: RenderSettings,
    gate: ThermalGate | NullGate | None = None,
) -> int:
    """Последовательный прогон серии (WP-N4): одна тяжёлая job за раз.

    Сервер (`POST /api/worker/series/next`) двигает item'ы, поэтому порядок,
    пауза и `stop_after_current` соблюдаются без отдельной очереди.

    WP-THERMAL-02: при тепловой паузе прогон ставится на штатную `pause`
    (только если паузу поставил сам планировщик — чужую он не снимает).
    """

    gate = gate or THERMAL_OFF
    run_id = getattr(args, "series_run", None)
    scheduler_paused = False
    while True:
        decision = gate.before_next()
        if not decision.allowed:
            if run_id and not scheduler_paused:
                try:
                    api.series_pause(run_id)
                    scheduler_paused = True
                    notify(
                        "Mary Studio: серия на паузе",
                        f"Термозащита: {decision.reason}",
                    )
                except WorkerError as error:
                    print(
                        f"warning: не удалось поставить паузу: {error}",
                        file=sys.stderr,
                    )
            if _wait_for_admission(gate, decision, args, series=True):
                return 1 if gate.should_stop_waiting() else 0
            continue
        if scheduler_paused and run_id:
            try:
                api.series_resume(run_id)
                scheduler_paused = False
                notify(
                    "Mary Studio: серия продолжена",
                    "Термозащита: условия снова в норме",
                )
            except WorkerError as error:
                print(
                    f"warning: не удалось снять паузу: {error}", file=sys.stderr
                )

        try:
            reply = api.series_next(args.name, run_id=run_id)
        except WorkerError as error:
            print(f"series/next failed: {error}", file=sys.stderr)
            time.sleep(args.poll)
            continue

        run_id = str(reply.get("run_id") or run_id or "") or None
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

        code = _process_job(api, job, args, settings, gate)
        if code != 0 and args.once:
            return code
        if args.once:
            return 0


def _build_thermal_gate(
    args: argparse.Namespace, profile: str | None = None
) -> ThermalGate | NullGate:
    """Собирает thermal-контроль по CLI-флагам (Q-27…Q-33).

    Профиль выбирается только при запуске воркера: серверного API для смены
    профиля нет, состояние в БД не пишется. `profile` позволяет передать
    значение из `RenderSettings`, чтобы источник был один.
    """

    profile = profile or args.thermal_profile
    helper = Path(args.thermal_helper)
    if args.build_thermal_helper:
        try:
            target = build_helper()
            print(f"thermal helper: собран {target}", file=sys.stderr)
        except (OSError, RuntimeError) as error:
            print(f"warning: thermal helper не собран: {error}", file=sys.stderr)
    if profile == "off":
        print("thermal profile: off (контроль отключён)", file=sys.stderr)
        return NullGate()
    if not helper.exists():
        print(
            f"warning: thermal helper не найден ({helper}): состояние unknown,"
            " действует консервативный режим (дольше cooldown, партия ≤ 2)",
            file=sys.stderr,
        )
    print(
        f"thermal profile: {profile} (state={args.thermal_state_file},"
        f" log={args.thermal_log}, caffeinate={args.caffeinate},"
        f" allow_battery={args.allow_battery})",
        file=sys.stderr,
    )
    return ThermalGate(
        profile=profile,
        worker_name=args.name,
        state_path=Path(args.thermal_state_file),
        log_path=Path(args.thermal_log),
        probes=Probes(helper=helper),
        poll_seconds=args.thermal_poll,
        max_wait_seconds=args.thermal_max_wait,
        allow_battery=args.allow_battery,
    )


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
    parser.add_argument(
        "--preset",
        default=None,
        help="имя пресета рендера (WP-M7); по умолчанию — рекомендация API",
    )
    parser.add_argument(
        "--no-preset",
        action="store_true",
        help="не запрашивать рекомендацию пресета, использовать встроенные значения",
    )
    parser.add_argument("--aspect-ratio", default=None)
    parser.add_argument("--long-side", type=int, default=None)
    parser.add_argument("--cfg-scale", type=float, default=None)
    parser.add_argument("--comfy-poll", type=float, default=5.0)
    parser.add_argument("--timeout", type=float, default=3600.0)
    parser.add_argument("--lease", type=int, default=300)
    parser.add_argument(
        "--state-file",
        default=os.environ.get("MARY_WORKER_STATE", str(DEFAULT_STATE_FILE)),
        help="state-файл с prompt_id незавершённых рендеров (WP-M4)",
    )
    parser.add_argument(
        "--thermal-profile",
        default=os.environ.get("MARY_THERMAL_PROFILE", "balanced"),
        choices=PROFILE_NAMES,
        help="thermal-safe профиль (WP-THERMAL-02): off|balanced|eco",
    )
    parser.add_argument(
        "--no-caffeinate",
        action="store_true",
        help="не удерживать систему от сна во время рендера (по умолчанию caffeinate -i)",
    )
    parser.add_argument(
        "--allow-battery",
        action="store_true",
        help="разрешить рендер от батареи с зарядом ≥ 50%% (только профиль eco)",
    )
    parser.add_argument(
        "--thermal-state-file",
        default=os.environ.get("MARY_THERMAL_STATE", str(DEFAULT_THERMAL_STATE)),
        help="файл состояния thermal-планировщика",
    )
    parser.add_argument(
        "--thermal-log",
        default=os.environ.get("MARY_THERMAL_LOG", str(DEFAULT_LOG_FILE)),
        help="JSONL-журнал thermal-событий",
    )
    parser.add_argument(
        "--thermal-helper",
        default=os.environ.get("MARY_THERMAL_HELPER", str(DEFAULT_HELPER)),
        help="Swift-helper ProcessInfo.thermalState",
    )
    parser.add_argument(
        "--build-thermal-helper",
        action="store_true",
        help="собрать Swift-helper через swiftc перед запуском",
    )
    parser.add_argument(
        "--thermal-poll",
        type=float,
        default=float(os.environ.get("MARY_THERMAL_POLL", "60")),
        help="период опроса состояния во время ожидания, с",
    )
    parser.add_argument(
        "--thermal-max-wait",
        type=float,
        default=float(os.environ.get("MARY_THERMAL_MAX_WAIT", "21600")),
        help="сколько ждать допуска в режиме серии, с (по умолчанию 6 ч)",
    )
    args = parser.parse_args(argv)
    args.caffeinate = not args.no_caffeinate

    if not args.token:
        parser.error("worker token is required (--token or MARY_WORKER_TOKEN)")

    api = WorkerClient(args.url, args.token)
    choice = resolve_preset(
        requested=args.preset,
        aspect_ratio=args.aspect_ratio,
        long_side=args.long_side,
        cfg_scale=args.cfg_scale,
        fetch=None if args.no_preset else api.get_presets,
    )
    if choice.warning is not None:
        print(f"warning: {choice.warning}", file=sys.stderr)
    print(
        f"render preset: {choice.preset or 'default'} ({choice.source}), "
        f"aspect={choice.aspect_ratio}, long_side={choice.long_side}, "
        f"cfg={choice.cfg_scale}",
        file=sys.stderr,
    )

    settings = RenderSettings(
        comfy_url=args.comfy_url,
        workflow_path=Path(args.workflow),
        aspect_ratio=choice.aspect_ratio,
        long_side=choice.long_side,
        cfg_scale=choice.cfg_scale,
        poll_interval=args.comfy_poll,
        render_timeout_s=args.timeout,
        lease_seconds=args.lease,
        preset=choice.preset,
        preset_source=choice.source,
        thermal_profile=args.thermal_profile,
        state_path=Path(args.state_file),
    )
    gate = _build_thermal_gate(args, settings.thermal_profile)
    _recover_at_startup(api, args, settings)
    if args.series or args.series_run:
        return _series_loop(api, args, settings, gate)
    return _job_loop(api, args, settings, gate)


if __name__ == "__main__":
    raise SystemExit(main())
