from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx


class ComfyUIClient:
    def __init__(self, base_url: str, timeout: float = 300.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def is_available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/system_stats")
                return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def get_object_info(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(f"{self.base_url}/object_info")
            response.raise_for_status()
            return response.json()

    async def queue_prompt(self, workflow: dict[str, Any], client_id: str | None = None) -> str:
        payload = {
            "prompt": workflow,
            "client_id": client_id or str(uuid.uuid4()),
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(f"{self.base_url}/prompt", json=payload)
            response.raise_for_status()
            data = response.json()
        prompt_id = data.get("prompt_id")
        if not prompt_id:
            raise ValueError(f"ComfyUI не вернул prompt_id: {data}")
        return prompt_id

    async def wait_for_prompt(
        self,
        prompt_id: str,
        poll_interval: float = 2.0,
        *,
        timeout: float | None = None,
        on_poll: Callable[[], None] | None = None,
    ) -> dict[str, Any]:
        """Ждёт запись в `/history`.

        `on_poll` вызывается перед каждой паузой между опросами: воркер
        использует его для heartbeat, иначе lease истечёт на долгом рендере.
        `timeout` ограничивает общее ожидание.
        """

        deadline = time.monotonic() + timeout if timeout is not None else None
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            while True:
                response = await client.get(f"{self.base_url}/history/{prompt_id}")
                response.raise_for_status()
                history = response.json()
                if prompt_id in history:
                    return history[prompt_id]
                if deadline is not None and time.monotonic() >= deadline:
                    raise TimeoutError(f"ComfyUI не завершил prompt {prompt_id} за {timeout}s")
                if on_poll is not None:
                    on_poll()
                await asyncio.sleep(poll_interval)

    async def get_image(self, filename: str, subfolder: str = "", folder_type: str = "output") -> bytes:
        params = {
            "filename": filename,
            "subfolder": subfolder,
            "type": folder_type,
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(f"{self.base_url}/view", params=params)
            response.raise_for_status()
            return response.content

    def extract_saved_images(self, history_entry: dict[str, Any]) -> list[dict[str, str]]:
        outputs = history_entry.get("outputs") or {}
        images: list[dict[str, str]] = []
        for node_output in outputs.values():
            for image in node_output.get("images") or []:
                images.append(
                    {
                        "filename": image.get("filename") or "",
                        "subfolder": image.get("subfolder") or "",
                        "type": image.get("type") or "output",
                    }
                )
        return [img for img in images if img["filename"]]

    async def upload_image(self, image_path: Path, subfolder: str = "mary_guiness") -> dict[str, str]:
        async with httpx.AsyncClient(timeout=60.0) as client:
            with image_path.open("rb") as handle:
                files = {"image": (image_path.name, handle, "image/png")}
                data = {"subfolder": subfolder, "type": "input", "overwrite": "true"}
                response = await client.post(f"{self.base_url}/upload/image", files=files, data=data)
                response.raise_for_status()
                payload = response.json()
        return {
            "name": payload.get("name") or image_path.name,
            "subfolder": payload.get("subfolder") or subfolder,
        }
