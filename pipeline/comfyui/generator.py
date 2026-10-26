from __future__ import annotations

import random
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pipeline.comfyui.client import ComfyUIClient
from pipeline.comfyui.workflows import (
    build_positive_prompt,
    load_json,
    load_pose_config,
    load_workflow_config,
    render_workflow,
    select_character_template,
)
from pipeline.config import CHARACTER_POSES, Settings
from pipeline.utils import load_character_bible


@dataclass
class SetupReport:
    comfyui_available: bool
    missing_nodes: list[str]
    missing_models: list[str]
    available_nodes: list[str]
    notes: list[str]


@dataclass
class GenerationResult:
    character: str
    pose: str
    template: str
    output_path: Path | None
    success: bool
    message: str


class ComfyUISetupChecker:
    NODE_CLASS_HINTS = {
        "ComfyUI_IPAdapter_plus": ["IPAdapter", "IPAdapterUnifiedLoader", "IPAdapterAdvanced"],
        "comfyui_controlnet_aux": ["OpenposePreprocessor"],
        "ComfyUI-VideoHelperSuite": ["VHS_VideoCombine"],
        "ComfyUI-AnimateDiff-Evolved": ["ADE_AnimateDiffLoader"],
        "ComfyUI-LTXVideo": ["EmptyLTXVLatentVideo", "LTXVConditioning"],
    }

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = ComfyUIClient(settings.comfyui_base_url)

    async def check(self) -> SetupReport:
        notes: list[str] = []
        workflow_cfg = load_workflow_config(self.settings.workflows_dir())
        required_nodes = workflow_cfg.get("required_custom_nodes") or []

        if not await self.client.is_available():
            missing_models = self._missing_models(workflow_cfg)
            return SetupReport(
                comfyui_available=False,
                missing_nodes=required_nodes,
                missing_models=missing_models,
                available_nodes=[],
                notes=["ComfyUI не запущен. Запустите через Pinokio и повторите check."],
            )

        object_info = await self.client.get_object_info()
        available = set(object_info.keys())
        missing_nodes = []
        for pack, hints in self.NODE_CLASS_HINTS.items():
            if not any(hint in available for hint in hints):
                missing_nodes.append(pack)

        missing_models = self._missing_models(workflow_cfg)
        if missing_nodes:
            notes.append("Установите custom nodes через ComfyUI Manager (см. scenario.md).")
        if missing_models:
            notes.append("Скачайте модели в ComfyUI/models/ (см. workflow_config.json).")

        return SetupReport(
            comfyui_available=True,
            missing_nodes=missing_nodes,
            missing_models=missing_models,
            available_nodes=sorted(available)[:20],
            notes=notes,
        )

    def _expected_models(self, workflow_cfg: dict[str, Any]) -> list[str]:
        return [
            workflow_cfg.get("checkpoint") or "",
            workflow_cfg.get("controlnet_openpose_sd15") or "",
            workflow_cfg.get("ltx_checkpoint") or "",
        ]

    def _missing_models(self, workflow_cfg: dict[str, Any]) -> list[str]:
        comfyui_root = self._resolve_comfyui_root()
        if not comfyui_root:
            return self._expected_models(workflow_cfg)

        missing: list[str] = []
        checks = [
            ("checkpoints", workflow_cfg.get("checkpoint"), True),
            ("controlnet", workflow_cfg.get("controlnet_openpose_sd15"), False),
            ("diffusion_models", workflow_cfg.get("ltx_checkpoint"), False),
        ]
        for folder, name, required in checks:
            if not name:
                continue
            path = comfyui_root / "models" / folder / name
            if not path.exists() and required:
                missing.append(f"{folder}/{name}")
            elif not path.exists() and not required:
                missing.append(f"{folder}/{name} (опционально)")
        return missing

    def _resolve_comfyui_root(self) -> Path | None:
        if self.settings.comfyui_root and self.settings.comfyui_root.exists():
            return self.settings.comfyui_root
        candidate = Path("/Users/vladislavkovalenko/Projects/RETRO_LINUX_TERMINAL_GAME/ComfyUI")
        return candidate if candidate.exists() else None


class CharacterReferenceGenerator:
    TEMPLATE_FILES = {
        "txt2img": "character_pose_gen.api.json",
        "openpose": "character_pose_openpose.api.json",
        "ipadapter": "character_pose_ipadapter.api.json",
    }

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = ComfyUIClient(settings.comfyui_base_url)
        self.workflow_cfg = load_workflow_config(settings.workflows_dir())
        self.pose_cfg = load_pose_config(settings.prompts_dir())

    async def generate_pose(
        self,
        character: str,
        pose_name: str,
        seed: int | None = None,
        force: bool = False,
    ) -> GenerationResult:
        if pose_name not in CHARACTER_POSES:
            return GenerationResult(character, pose_name, "", None, False, f"Неизвестная поза: {pose_name}")

        output_path = self.settings.character_dir(character) / f"{pose_name}.png"
        if output_path.exists() and not force:
            return GenerationResult(
                character, pose_name, "existing", output_path, True, "Референс уже существует"
            )

        if not await self.client.is_available():
            return GenerationResult(character, pose_name, "", None, False, "ComfyUI недоступен")

        bible = load_character_bible(self.settings.character_dir(character) / "character_bible.txt")
        if not bible:
            return GenerationResult(character, pose_name, "", None, False, "character_bible.txt пуст")

        pose_meta = self.pose_cfg[pose_name]
        anchor_pose = pose_meta.get("anchor_pose")
        anchor_path = (
            self.settings.character_dir(character) / f"{anchor_pose}.png"
            if anchor_pose
            else None
        )
        skeleton_path = self.settings.project_root / "comfyui-input" / "poses" / f"{pose_name}.png"
        template_key = select_character_template(
            pose_name,
            pose_meta,
            anchor_exists=bool(anchor_path and anchor_path.exists()),
            pose_skeleton_exists=skeleton_path.exists(),
        )
        template_file = self.TEMPLATE_FILES[template_key]
        template = load_json(self.settings.workflows_dir() / template_file)

        variables = self._build_variables(
            character=character,
            pose_name=pose_name,
            pose_meta=pose_meta,
            bible=bible,
            template_key=template_key,
            anchor_path=anchor_path,
            skeleton_path=skeleton_path,
            seed=seed or random.randint(1, 2**31 - 1),
        )

        try:
            workflow = render_workflow(template, variables)
        except KeyError as exc:
            return GenerationResult(character, pose_name, template_key, None, False, str(exc))

        if template_key == "ipadapter" and anchor_path and anchor_path.exists():
            uploaded = await self.client.upload_image(
                anchor_path,
                subfolder="",
            )
            workflow = self._patch_load_image(workflow, uploaded["name"])

        prompt_id = await self.client.queue_prompt(workflow)
        history = await self.client.wait_for_prompt(prompt_id)
        images = self.client.extract_saved_images(history)
        if not images:
            return GenerationResult(
                character, pose_name, template_key, None, False, "ComfyUI не сохранил изображение"
            )

        image_meta = images[-1]
        content = await self.client.get_image(
            image_meta["filename"],
            subfolder=image_meta["subfolder"],
            folder_type=image_meta["type"],
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(content)

        return GenerationResult(
            character,
            pose_name,
            template_key,
            output_path,
            True,
            f"Сохранено через {template_key}",
        )

    async def generate_all(
        self,
        character: str,
        force: bool = False,
        skip_front: bool = False,
    ) -> list[GenerationResult]:
        results: list[GenerationResult] = []
        poses = CHARACTER_POSES[1:] if skip_front else CHARACTER_POSES

        if skip_front:
            front_path = self.settings.character_dir(character) / "reference_front.png"
            if not front_path.exists():
                return [
                    GenerationResult(
                        character, "reference_front", "", None, False,
                        "Загрузите reference_front.png перед генерацией остальных поз",
                    )
                ]

        for pose_name in poses:
            result = await self.generate_pose(character, pose_name, force=force)
            results.append(result)
            if not result.success and pose_name == "reference_front":
                break
        return results

    def _build_variables(
        self,
        character: str,
        pose_name: str,
        pose_meta: dict[str, Any],
        bible: str,
        template_key: str,
        anchor_path: Path | None,
        skeleton_path: Path,
        seed: int,
    ) -> dict[str, Any]:
        positive = build_positive_prompt(
            bible,
            pose_meta.get("pose_prompt") or pose_name,
            character_kind="cat" if character == "guinness" else "human",
        )
        variables: dict[str, Any] = {
            "CHECKPOINT": self.workflow_cfg.get("checkpoint"),
            "POSITIVE_PROMPT": positive,
            "NEGATIVE_PROMPT": self.workflow_cfg.get("negative_prompt"),
            "OUTPUT_PREFIX": f"mary_guiness/{character}/{pose_name}",
            "SEED": seed,
            "WIDTH": self.workflow_cfg.get("width", 512),
            "HEIGHT": self.workflow_cfg.get("height", 768),
            "STEPS": self.workflow_cfg.get("steps", 28),
            "CFG": self.workflow_cfg.get("cfg", 7.5),
            "SAMPLER": self.workflow_cfg.get("sampler", "dpmpp_2m"),
            "SCHEDULER": self.workflow_cfg.get("scheduler", "karras"),
            "CONTROLNET": self.workflow_cfg.get("controlnet_openpose_sd15"),
            "CONTROLNET_STRENGTH": self.workflow_cfg.get("controlnet_strength", 0.85),
            "IPADAPTER_WEIGHT": self.workflow_cfg.get("ipadapter_weight", 0.75),
            "POSE_IMAGE": skeleton_path.name if skeleton_path.exists() else "poses/placeholder.png",
            "REFERENCE_IMAGE": anchor_path.name if anchor_path and anchor_path.exists() else "",
        }

        if template_key == "openpose" and skeleton_path.exists():
            # upload handled separately in future; for now expect file in ComfyUI/input
            comfy_input = self._copy_to_comfyui_input(skeleton_path)
            variables["POSE_IMAGE"] = comfy_input.name

        if template_key == "ipadapter" and anchor_path and anchor_path.exists():
            comfy_ref = self._copy_to_comfyui_input(anchor_path, f"{character}_{anchor_path.name}")
            variables["REFERENCE_IMAGE"] = comfy_ref.name

        return variables

    def _patch_load_image(self, workflow: dict, image_name: str) -> dict:
        patched = dict(workflow)
        for node in patched.values():
            if node.get("class_type") == "LoadImage":
                node["inputs"]["image"] = image_name
        return patched

    def _copy_to_comfyui_input(self, source: Path, dest_name: str | None = None) -> Path:
        comfy_root = ComfyUISetupChecker(self.settings)._resolve_comfyui_root()
        if not comfy_root:
            return source
        target_dir = comfy_root / "input" / "mary_guiness"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / (dest_name or source.name)
        if not target.exists() or target.stat().st_size != source.stat().st_size:
            shutil.copy2(source, target)
        return target
