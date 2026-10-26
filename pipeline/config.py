from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent

CHARACTER_POSES = [
    "reference_front",
    "reference_side",
    "reference_3q",
    "reference_sit",
    "reference_walk",
    "reference_surprised",
    "reference_sleep",
]

CHARACTERS = ("guinness", "marija")


@dataclass(frozen=True)
class Settings:
    project_root: Path
    ollama_base_url: str
    ollama_model: str
    comfyui_base_url: str
    comfyui_root: Path | None
    grok_api_key: str | None
    kling_api_key: str | None
    elevenlabs_api_key: str | None
    hedra_api_key: str | None
    suno_api_key: str | None
    litellm_model: str

    @classmethod
    def from_env(cls, project_root: Path | None = None) -> Settings:
        root = project_root or PROJECT_ROOT
        return cls(
            project_root=root,
            ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/"),
            ollama_model=os.getenv("OLLAMA_MODEL", "catshow"),
            comfyui_base_url=os.getenv("COMFYUI_BASE_URL", "http://127.0.0.1:8188").rstrip("/"),
            comfyui_root=Path(root_env).expanduser() if (root_env := os.getenv("COMFYUI_ROOT")) else None,
            grok_api_key=os.getenv("GROK_API_KEY") or None,
            kling_api_key=os.getenv("KLING_API_KEY") or None,
            elevenlabs_api_key=os.getenv("ELEVENLABS_API_KEY") or None,
            hedra_api_key=os.getenv("HEDRA_API_KEY") or None,
            suno_api_key=os.getenv("SUNO_API_KEY") or None,
            litellm_model=os.getenv("LITELLM_MODEL", f"ollama/{os.getenv('OLLAMA_MODEL', 'catshow')}"),
        )

    def character_dir(self, name: str) -> Path:
        return self.project_root / "characters" / name

    def episode_dir(self, episode_id: str) -> Path:
        return self.project_root / "episodes" / episode_id

    def prompts_dir(self) -> Path:
        return self.project_root / "prompts"

    def workflows_dir(self) -> Path:
        return self.project_root / "comfyui-workflows"

    def exports_dir(self) -> Path:
        return self.project_root / "exports"
