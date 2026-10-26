"""Visual Scene Planner (WP-05A).

Детерминированная часть: alias и связи с референсами задаёт сервер, структура
плана валидируется здесь же. LLM/vision (`gemma3:4b`) — только советующий
источник наблюдений: он не возвращает asset_id/entity_id и не может изменить
утверждённые данные. Любая ошибка модели даёт `source='fallback'`.
"""

from __future__ import annotations

import base64
import io
import json
import re
import uuid
from dataclasses import dataclass
from typing import Any

import httpx
from PIL import Image

PLAN_SCHEMA_VERSION = 1
DEFAULT_CANVAS = (768, 512)

REFERENCE_ROLES = ("character", "location", "prop", "style", "storyboard")
CAMERA_FRAMINGS = ("wide", "medium", "close_up", "other")
CAMERA_MOVEMENTS = ("static", "pan", "tilt", "dolly", "zoom", "handheld", "other")
MAX_MOTION_PROMPT = 4000
_ALIAS_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")

_CONSTRAINT_DEFAULTS = {
    "preserve_character_identity": True,
    "preserve_location_layout": True,
    "no_unreferenced_characters": True,
}

_VISION_PROMPT = """You are a visual continuity assistant for an animation studio.
You receive reference images, each labelled with an alias.
Return STRICT JSON only, matching this schema:
{{
  "observations": [
    {{"alias": "<one of: {aliases}>", "subject": "<what is visible>",
      "pose": "<apparent pose>", "facing": "<direction the subject faces>",
      "visibility": "<full|partial|occluded>"}}
  ],
  "uncertainties": ["<short phrase>"]
}}
Rules:
- Use only the given aliases; never invent new ones.
- Describe only what is actually visible; do not invent background objects.
- If a detail is unclear, put it in "uncertainties" instead of guessing.
Scene action to illustrate: {action}
"""


class PlanError(ValueError):
    """План нарушает схему (422)."""


class PlannerUnavailable(RuntimeError):
    """Vision/LLM недоступен: используется детерминированный fallback."""


@dataclass(frozen=True)
class PlanReference:
    asset_id: uuid.UUID
    role: str
    entity_id: uuid.UUID | None
    alias: str


def default_canvas(width: int | None, height: int | None) -> tuple[int, int]:
    return (
        width if width is not None else DEFAULT_CANVAS[0],
        height if height is not None else DEFAULT_CANVAS[1],
    )


def build_skeleton(
    references: list[PlanReference],
    *,
    action: str,
    camera: dict[str, str] | None,
    canvas: tuple[int, int],
) -> dict[str, Any]:
    resolved_camera = {
        "framing": (camera or {}).get("framing", "wide"),
        "movement": (camera or {}).get("movement", "static"),
    }
    plan: dict[str, Any] = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "canvas": {"width": canvas[0], "height": canvas[1]},
        "references": [
            {
                "asset_id": str(reference.asset_id),
                "role": reference.role,
                "entity_id": str(reference.entity_id)
                if reference.entity_id is not None
                else None,
                "alias": reference.alias,
            }
            for reference in references
        ],
        "camera": resolved_camera,
        "initial_state": [],
        "action_beats": [],
        "constraints": dict(_CONSTRAINT_DEFAULTS),
        "motion_prompt": motion_prompt(resolved_camera, action),
        "needs_review": False,
    }
    return plan


def motion_prompt(camera: dict[str, str], action: str) -> str:
    """Детерминированный шаблон: без литературных вольностей модели."""

    framing = camera.get("framing", "wide")
    movement = camera.get("movement", "static")
    text = f"{framing} shot, {movement} camera"
    action = action.strip()
    if action:
        text = f"{text}; {action}"
    return text[:MAX_MOTION_PROMPT]


def validate_plan(plan: dict[str, Any]) -> None:
    """Проверяет структуру плана; ссылки на ассеты проверяет API."""

    if not isinstance(plan, dict):
        raise PlanError("plan must be an object")
    if plan.get("schema_version") != PLAN_SCHEMA_VERSION:
        raise PlanError(f"unsupported plan schema_version: {plan.get('schema_version')!r}")

    canvas = plan.get("canvas")
    if not isinstance(canvas, dict):
        raise PlanError("canvas must be an object")
    width, height = canvas.get("width"), canvas.get("height")
    if not isinstance(width, int) or not isinstance(height, int):
        raise PlanError("canvas width/height must be integers")
    if width <= 0 or height <= 0:
        raise PlanError("canvas width/height must be positive")

    references = plan.get("references")
    if not isinstance(references, list) or not references:
        raise PlanError("plan needs at least one reference")
    aliases: set[str] = set()
    for item in references:
        if not isinstance(item, dict):
            raise PlanError("each reference must be an object")
        alias = item.get("alias")
        if not isinstance(alias, str) or not _ALIAS_RE.match(alias):
            raise PlanError(f"invalid reference alias: {alias!r}")
        if alias in aliases:
            raise PlanError(f"duplicate reference alias: {alias}")
        aliases.add(alias)
        if item.get("role") not in REFERENCE_ROLES:
            raise PlanError(f"invalid reference role: {item.get('role')!r}")
        try:
            uuid.UUID(str(item.get("asset_id")))
        except (ValueError, TypeError) as error:
            raise PlanError("reference asset_id must be a UUID") from error
        entity_id = item.get("entity_id")
        if entity_id is not None:
            try:
                uuid.UUID(str(entity_id))
            except (ValueError, TypeError) as error:
                raise PlanError("reference entity_id must be a UUID") from error

    camera = plan.get("camera")
    if not isinstance(camera, dict):
        raise PlanError("camera must be an object")
    if camera.get("framing") not in CAMERA_FRAMINGS:
        raise PlanError(f"invalid camera framing: {camera.get('framing')!r}")
    if camera.get("movement") not in CAMERA_MOVEMENTS:
        raise PlanError(f"invalid camera movement: {camera.get('movement')!r}")

    initial_state = plan.get("initial_state", [])
    if not isinstance(initial_state, list):
        raise PlanError("initial_state must be a list")
    for entry in initial_state:
        _validate_subject_entry(entry, aliases, "initial_state")

    beats = plan.get("action_beats", [])
    if not isinstance(beats, list):
        raise PlanError("action_beats must be a list")
    orders: list[int] = []
    for beat in beats:
        _validate_subject_entry(beat, aliases, "action_beats")
        order = beat.get("order")
        if not isinstance(order, int) or order < 1:
            raise PlanError("action beat order must be a positive integer")
        orders.append(order)
        target = beat.get("target")
        if target is not None and target not in aliases:
            raise PlanError(f"action beat target is not a declared alias: {target!r}")
    if orders and sorted(orders) != list(range(1, len(orders) + 1)):
        raise PlanError("action beat order must be 1..N without gaps")

    constraints = plan.get("constraints", {})
    if not isinstance(constraints, dict):
        raise PlanError("constraints must be an object")
    for key, value in constraints.items():
        if key in _CONSTRAINT_DEFAULTS and not isinstance(value, bool):
            raise PlanError(f"constraint {key} must be a boolean")

    prompt = plan.get("motion_prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise PlanError("motion_prompt must be a non-empty string")
    if len(prompt) > MAX_MOTION_PROMPT:
        raise PlanError(f"motion_prompt exceeds {MAX_MOTION_PROMPT} characters")

    if not isinstance(plan.get("needs_review"), bool):
        raise PlanError("needs_review must be a boolean")


def _validate_subject_entry(entry: Any, aliases: set[str], field: str) -> None:
    if not isinstance(entry, dict):
        raise PlanError(f"{field} entries must be objects")
    subject = entry.get("subject")
    if subject not in aliases:
        raise PlanError(f"{field} subject is not a declared alias: {subject!r}")
    for key in ("position", "action"):
        value = entry.get(key)
        if value is not None and not isinstance(value, str):
            raise PlanError(f"{field} {key} must be a string")


def normalize_vision_response(
    raw: str,
    references: list[PlanReference],
    plan: dict[str, Any],
) -> list[dict[str, str]]:
    """Переносит наблюдения модели в initial_state, отбрасывая галлюцинации.

    Возвращает список предупреждений; `plan` изменяется на месте.
    """

    warnings: list[dict[str, str]] = []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise PlannerUnavailable("vision returned invalid JSON") from error
    if not isinstance(payload, dict):
        raise PlannerUnavailable("vision returned a non-object JSON")

    known = {reference.alias for reference in references}
    observations = payload.get("observations")
    if not isinstance(observations, list):
        observations = []

    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for observation in observations:
        if not isinstance(observation, dict):
            continue
        alias = observation.get("alias")
        if alias not in known:
            warnings.append(
                {
                    "code": "vision_alias_mismatch",
                    "message": f"Наблюдение модели для неизвестного alias '{alias}' отброшено.",
                }
            )
            continue
        if alias in seen:
            continue
        seen.add(alias)
        pose = observation.get("pose") if isinstance(observation.get("pose"), str) else ""
        facing = (
            observation.get("facing") if isinstance(observation.get("facing"), str) else ""
        )
        subject = (
            observation.get("subject")
            if isinstance(observation.get("subject"), str)
            else ""
        )
        position = "; ".join(
            part for part in (subject.strip(), facing.strip()) if part
        )
        entries.append(
            {
                "subject": alias,
                "position": position,
                "action": pose.strip(),
            }
        )

    plan["initial_state"] = entries
    uncertainties = payload.get("uncertainties")
    if isinstance(uncertainties, list):
        for item in uncertainties:
            if isinstance(item, str) and item.strip():
                warnings.append(
                    {
                        "code": "vision_uncertainty",
                        "message": f"Модель не уверена: {item.strip()}",
                    }
                )
    if not entries:
        plan["needs_review"] = True
        warnings.append(
            {
                "code": "vision_no_observations",
                "message": "Модель не дала пригодных наблюдений; план требует ручной проверки.",
            }
        )
    return warnings


def analyze_images(
    images: list[tuple[str, bytes]],
    *,
    aliases: list[str],
    action: str,
    settings: Any,
) -> str:
    """Отправляет изображения в Ollama и возвращает сырой JSON-ответ модели."""

    prepared: list[str] = []
    for _alias, data in images:
        prepared.append(base64.b64encode(_downscale(data, settings.planner_image_max_side)).decode())

    payload = {
        "model": settings.planner_model,
        "prompt": _VISION_PROMPT.format(
            aliases=", ".join(aliases), action=action or "(not specified)"
        ),
        "images": prepared,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0},
    }
    try:
        data = _request_ollama(payload, settings)
    except (httpx.HTTPError, ValueError, KeyError) as error:
        raise PlannerUnavailable(str(error)) from error
    response = data.get("response")
    if not isinstance(response, str) or not response.strip():
        raise PlannerUnavailable("vision returned an empty response")
    return response


def _request_ollama(payload: dict[str, Any], settings: Any) -> dict[str, Any]:
    url = f"{settings.ollama_base_url.rstrip('/')}/api/generate"
    with httpx.Client(timeout=settings.planner_timeout_s) as client:
        response = client.post(url, json=payload)
        response.raise_for_status()
        return response.json()


def _downscale(data: bytes, max_side: int) -> bytes:
    try:
        with Image.open(io.BytesIO(data)) as opened:
            image = opened.convert("RGB")
            if max(image.size) > max_side:
                image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            return buffer.getvalue()
    except Exception as error:  # noqa: BLE001 - любое повреждение изображения
        raise ValueError(f"cannot prepare image for vision: {error}") from error


def generate_candidate(
    references: list[PlanReference],
    *,
    action: str,
    camera: dict[str, str] | None,
    canvas: tuple[int, int],
    images: list[tuple[str, bytes]],
    use_vision: bool,
    settings: Any,
) -> tuple[dict[str, Any], list[dict[str, str]], str]:
    """Возвращает (plan, warnings, source) для предпросмотра в UI."""

    plan = build_skeleton(references, action=action, camera=camera, canvas=canvas)
    warnings: list[dict[str, str]] = []
    source = "manual"

    if use_vision and images:
        source = "llm"
        try:
            raw = analyze_images(
                images,
                aliases=[reference.alias for reference in references],
                action=action,
                settings=settings,
            )
            warnings.extend(normalize_vision_response(raw, references, plan))
        except PlannerUnavailable as error:
            source = "fallback"
            plan["needs_review"] = True
            warnings.append(
                {
                    "code": "vision_unavailable",
                    "message": f"Vision недоступен ({error}); использован детерминированный план.",
                }
            )

    validate_plan(plan)
    return plan, warnings, source
