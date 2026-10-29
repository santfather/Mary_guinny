"""Клиент worker API Mary Studio (WP-06, вынесен в WP-N3).

Модуль общий для воркеров: `worker/fake_worker.py` (ffmpeg) и
`worker/ltx_worker.py` (ComfyUI LTX-2.3 MLX). Здесь только HTTP-вызовы
существующего контракта `/api/worker/*` и локальная проверка результата,
чтобы оба воркера не дублировали протокол.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
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
        parameters: dict[str, object] | None = None,
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
                "parameters": parameters,
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

    def series_next(
        self, worker_name: str, *, run_id: str | None = None
    ) -> dict[str, object]:
        """Следующий шаг прогона серии (WP-N4): `queued` / `running` / `paused`…

        Без `run_id` сервер берёт единственный активный прогон.
        """

        body: dict[str, object] = {"worker_name": worker_name}
        if run_id:
            body["run_id"] = run_id
        result = self._request("POST", "/api/worker/series/next", body=body)
        return dict(result or {})

    def download(self, content_url: str, destination: Path) -> str:
        request = urllib.request.Request(self.base_url + content_url)
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            data = response.read()
        destination.write_bytes(data)
        return hashlib.sha256(data).hexdigest()


def probe_duration(path: Path, *, ffprobe: str = "ffprobe") -> tuple[float, bool]:
    """Локальная проверка медиа перед отправкой (ffprobe)."""

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
