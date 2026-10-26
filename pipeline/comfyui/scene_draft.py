from __future__ import annotations

import asyncio
import random
import shutil
from dataclasses import dataclass
from pathlib import Path

from pipeline.comfyui.client import ComfyUIClient
from pipeline.comfyui.workflows import (
    build_scene_prompt,
    load_json,
    load_workflow_config,
    render_workflow,
)
from pipeline.config import Settings
from pipeline.models import Scene
from pipeline.utils import load_character_bible, parse_script


@dataclass
class SceneDraftResult:
    scene_number: int
    output_path: Path | None
    keyframe_path: Path | None
    success: bool
    message: str


class SceneDraftGenerator:
    TEMPLATE = "scene_draft_ipadapter.api.json"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = ComfyUIClient(settings.comfyui_base_url)
        self.workflow_cfg = load_workflow_config(settings.workflows_dir())

    async def generate_scene(
        self,
        episode_id: str,
        scene: Scene,
        seed: int | None = None,
        force: bool = False,
    ) -> SceneDraftResult:
        scenes_dir = self.settings.episode_dir(episode_id) / "scenes"
        scenes_dir.mkdir(parents=True, exist_ok=True)

        output_mp4 = scenes_dir / f"scene_{scene.number:02d}_draft.mp4"
        keyframe_png = scenes_dir / f"scene_{scene.number:02d}_keyframe.png"

        if output_mp4.exists() and not force:
            return SceneDraftResult(
                scene.number, output_mp4, keyframe_png if keyframe_png.exists() else None,
                True, "Черновик уже существует",
            )

        if not await self.client.is_available():
            return SceneDraftResult(scene.number, None, None, False, "ComfyUI недоступен")

        guinness_bible = load_character_bible(
            self.settings.character_dir("guinness") / "character_bible.txt"
        )
        marija_bible = load_character_bible(
            self.settings.character_dir("marija") / "character_bible.txt"
        )
        reference = self._pick_reference_image()
        if not reference:
            return SceneDraftResult(scene.number, None, None, False, "Нет референса Guinness")

        template = load_json(self.settings.workflows_dir() / self.TEMPLATE)
        positive = build_scene_prompt(
            scene.action or "",
            scene.title,
            guinness_bible,
            marija_bible,
        )
        variables = {
            "CHECKPOINT": self.workflow_cfg.get("checkpoint"),
            "POSITIVE_PROMPT": positive,
            "NEGATIVE_PROMPT": self.workflow_cfg.get("negative_prompt"),
            "OUTPUT_PREFIX": f"mary_guiness/ep{episode_id}/scene_{scene.number:02d}",
            "SEED": seed or random.randint(1, 2**31 - 1),
            "WIDTH": self.workflow_cfg.get("scene_width", 768),
            "HEIGHT": self.workflow_cfg.get("scene_height", 512),
            "STEPS": self.workflow_cfg.get("steps", 28),
            "CFG": self.workflow_cfg.get("cfg", 7.5),
            "SAMPLER": self.workflow_cfg.get("sampler", "dpmpp_2m"),
            "SCHEDULER": self.workflow_cfg.get("scheduler", "karras"),
            "IPADAPTER_WEIGHT": self.workflow_cfg.get("ipadapter_weight", 0.75),
            "REFERENCE_IMAGE": reference.name,
        }

        workflow = render_workflow(template, variables)
        uploaded = await self.client.upload_image(reference, subfolder="")
        workflow = self._patch_load_image(workflow, uploaded["name"])

        prompt_id = await self.client.queue_prompt(workflow)
        history = await self.client.wait_for_prompt(prompt_id)
        images = self.client.extract_saved_images(history)
        if not images:
            return SceneDraftResult(scene.number, None, None, False, "ComfyUI не сохранил кадр")

        image_meta = images[-1]
        content = await self.client.get_image(
            image_meta["filename"],
            subfolder=image_meta["subfolder"],
            folder_type=image_meta["type"],
        )
        keyframe_png.write_bytes(content)

        duration = self.workflow_cfg.get("scene_duration_sec", 5)
        fps = self.workflow_cfg.get("scene_fps", 24)
        await self._image_to_mp4(keyframe_png, output_mp4, duration=duration, fps=fps)

        return SceneDraftResult(
            scene.number, output_mp4, keyframe_png, True, "Черновик собран из keyframe + ffmpeg",
        )

    async def generate_all(
        self,
        episode_id: str,
        force: bool = False,
    ) -> list[SceneDraftResult]:
        script_path = self.settings.episode_dir(episode_id) / "script.txt"
        scenes = parse_script(script_path.read_text(encoding="utf-8"))
        if not scenes:
            return []

        results: list[SceneDraftResult] = []
        for scene in scenes:
            result = await self.generate_scene(episode_id, scene, force=force)
            results.append(result)
            if not result.success:
                break
        return results

    def _pick_reference_image(self) -> Path | None:
        char_dir = self.settings.character_dir("guinness")
        for name in ("reference_3q.png", "reference_front.png"):
            path = char_dir / name
            if path.exists():
                return path
        return None

    def _patch_load_image(self, workflow: dict, image_name: str) -> dict:
        patched = dict(workflow)
        for node in patched.values():
            if node.get("class_type") == "LoadImage":
                node["inputs"]["image"] = image_name
        return patched

    async def _image_to_mp4(
        self,
        image_path: Path,
        output_path: Path,
        duration: int = 5,
        fps: int = 24,
    ) -> None:
        if not shutil.which("ffmpeg"):
            raise RuntimeError("ffmpeg не найден в PATH")

        cmd = [
            "ffmpeg", "-y",
            "-loop", "1",
            "-i", str(image_path),
            "-c:v", "libx264",
            "-t", str(duration),
            "-r", str(fps),
            "-pix_fmt", "yuv420p",
            "-vf", f"scale={self.workflow_cfg.get('scene_width', 768)}:{self.workflow_cfg.get('scene_height', 512)}",
            str(output_path),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {stderr.decode()[:500]}")
