"""Черновой производственный план песни (WP-M3).

Границы сцен и таймкоды определяет сервер из таймлайна: LLM только наполняет
их смыслом (заголовок, задача сцены, раскадровка, motion-промпт). Так модель не
может «переписать» структуру песни. Ответ модели валидируется Pydantic-схемой,
при ошибке — не более двух попыток repair; исчерпание попыток даёт
детерминированный каркас с `needs_review=true`.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

PLAN_SCHEMA_VERSION = 1
MAX_SCENES = 12
MAX_SHOTS_PER_SCENE = 6
MAX_TITLE = 120
MAX_TEXT = 600
MAX_PROMPT = 2000
MAX_NOTES = 12
MAX_REPAIR_ATTEMPTS = 2
DEFAULT_SHOT_SECONDS = 4.0

ENERGY_TIERS = ("low", "mid", "high")
CAMERA_FRAMINGS = ("wide", "medium", "close_up", "other")
CAMERA_MOVEMENTS = ("static", "pan", "tilt", "dolly", "zoom", "handheld", "other")

_DEFAULT_PROMPTS = {
    "low": "slow cinematic camera, gentle continuous motion, no text",
    "mid": "steady cinematic camera, characters move to the beat, no text",
    "high": "energetic cinematic camera, fast motion to the beat, no text",
}

_PLAN_PROMPT = """You are a production planner for a vertical music video (9:16).
Project: {title}
Brief: {brief}
Audio: {duration_s} s, {bpm}
Timeline sections are fixed by the server; do not change their timing:
{sections}
Library (use only these names):
characters: {characters}
locations: {locations}
props: {props}

Return STRICT JSON only:
{{
  "logline": "<one sentence>",
  "scenes": [
    {{
      "section_index": 0,
      "title": "<short scene title in Russian>",
      "intent": "<what the scene achieves, Russian>",
      "shots": [
        {{
          "action": "<what happens, Russian>",
          "prompt": "<English motion prompt for an image-to-video model>",
          "framing": "wide|medium|close_up|other",
          "camera_movement": "static|pan|tilt|dolly|zoom|handheld|other"
        }}
      ]
    }}
  ],
  "notes": ["<short production note, Russian>"]
}}
Rules:
- exactly one scene per section_index, no extra sections;
- {min_shots}..{max_shots} shots per scene;
- shot timing is assigned by the server, do not send timestamps;
- "prompt" is English, describes motion only, no dialogue or on-screen text;
- never invent characters, locations or props outside the library.
"""


class PlanError(ValueError):
    """План не соответствует схеме."""


class PlanShot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order: int = Field(ge=1)
    start_s: float = Field(ge=0)
    end_s: float = Field(gt=0)
    action: str = ""
    prompt: str
    framing: str
    camera_movement: str


class PlanScene(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order: int = Field(ge=1)
    section_index: int = Field(ge=0)
    title: str
    intent: str = ""
    energy_tier: str
    start_s: float = Field(ge=0)
    end_s: float = Field(gt=0)
    shots: list[PlanShot] = Field(min_length=1, max_length=MAX_SHOTS_PER_SCENE)


class ProductionPlanPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int
    logline: str = ""
    scenes: list[PlanScene] = Field(min_length=1, max_length=MAX_SCENES)
    notes: list[str] = Field(default_factory=list, max_length=MAX_NOTES)
    needs_review: bool = True


def _text(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()[:limit]


def _choice(value: Any, allowed: tuple[str, ...], default: str) -> str:
    return value if isinstance(value, str) and value in allowed else default


def _nearest(values: list[float], target: float) -> float | None:
    if not values:
        return None
    return min(values, key=lambda value: abs(value - target))


def _shot_count(length_s: float) -> int:
    if length_s <= 0:
        return 1
    return max(1, min(MAX_SHOTS_PER_SCENE, int(round(length_s / DEFAULT_SHOT_SECONDS)) or 1))


def _split_shots(
    start: float, end: float, downbeats: list[float], count: int, energy_tier: str
) -> list[dict[str, Any]]:
    """Делит секцию на равные шоты и подтягивает внутренние границы к долям."""

    count = max(1, min(MAX_SHOTS_PER_SCENE, count))
    length = end - start
    step = length / count
    boundaries = [start + step * index for index in range(count + 1)]
    boundaries[0] = start
    boundaries[-1] = end
    for index in range(1, count):
        nearest = _nearest(downbeats, boundaries[index])
        if (
            nearest is not None
            and start < nearest < end
            and abs(nearest - boundaries[index]) <= 0.15 * step
        ):
            boundaries[index] = nearest
    if any(boundaries[index] <= boundaries[index - 1] for index in range(1, len(boundaries))):
        boundaries = [start + step * index for index in range(count + 1)]
        boundaries[-1] = end

    prompt = _DEFAULT_PROMPTS.get(energy_tier, _DEFAULT_PROMPTS["mid"])
    shots: list[dict[str, Any]] = []
    for index in range(count):
        shots.append(
            {
                "order": index + 1,
                "start_s": round(boundaries[index], 2),
                "end_s": round(boundaries[index + 1], 2),
                "action": "",
                "prompt": prompt,
                "framing": "wide",
                "camera_movement": "static",
            }
        )
    return shots


def build_skeleton(timeline: dict[str, Any]) -> dict[str, Any]:
    """Детерминированный каркас: сцены = энергетические секции таймлайна."""

    duration = float(timeline.get("duration_s") or 0.0)
    if duration <= 0:
        raise PlanError("таймлайн без длительности")
    downbeats = [
        float(value) for value in timeline.get("downbeats") or [] if isinstance(value, (int, float))
    ]

    sections: list[tuple[float, float, str]] = []
    for section in timeline.get("sections") or []:
        if not isinstance(section, dict):
            continue
        try:
            start = max(0.0, float(section.get("start_s")))
            end = min(duration, float(section.get("end_s")))
        except (TypeError, ValueError):
            continue
        if end <= start:
            continue
        tier = _choice(section.get("energy_tier"), ENERGY_TIERS, "mid")
        sections.append((start, end, tier))
        if len(sections) >= MAX_SCENES:
            break
    if not sections:
        sections = [(0.0, duration, "mid")]

    scenes: list[dict[str, Any]] = []
    for index, (start, end, tier) in enumerate(sections):
        scenes.append(
            {
                "order": index + 1,
                "section_index": index,
                "title": f"Сцена {index + 1}",
                "intent": "",
                "energy_tier": tier,
                "start_s": round(start, 2),
                "end_s": round(end, 2),
                "shots": _split_shots(start, end, downbeats, _shot_count(end - start), tier),
            }
        )

    return {
        "schema_version": PLAN_SCHEMA_VERSION,
        "logline": "",
        "scenes": scenes,
        "notes": [],
        "needs_review": True,
    }


def validate_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Pydantic-схема + семантические проверки; возвращает нормализованный план."""

    try:
        payload = ProductionPlanPayload.model_validate(plan)
    except Exception as error:  # noqa: BLE001 - любая ошибка схемы = PlanError
        raise PlanError(str(error)) from error
    if payload.schema_version != PLAN_SCHEMA_VERSION:
        raise PlanError(f"unsupported plan schema_version: {payload.schema_version}")
    if len(payload.logline) > MAX_TEXT:
        raise PlanError(f"logline exceeds {MAX_TEXT} characters")

    previous_end = 0.0
    for scene_index, scene in enumerate(payload.scenes, start=1):
        if scene.order != scene_index:
            raise PlanError("scene order must be 1..N without gaps")
        if scene.end_s <= scene.start_s:
            raise PlanError(f"scene {scene.order}: end_s must be greater than start_s")
        if scene.start_s + 0.01 < previous_end:
            raise PlanError(f"scene {scene.order}: overlaps the previous scene")
        previous_end = scene.end_s
        if scene.energy_tier not in ENERGY_TIERS:
            raise PlanError(f"scene {scene.order}: invalid energy_tier")
        if not scene.title:
            raise PlanError(f"scene {scene.order}: title is empty")
        if len(scene.title) > MAX_TITLE:
            raise PlanError(f"scene {scene.order}: title is too long")
        if len(scene.intent) > MAX_TEXT:
            raise PlanError(f"scene {scene.order}: intent is too long")

        previous_shot_end = scene.start_s - 0.01
        for shot_index, shot in enumerate(scene.shots, start=1):
            if shot.order != shot_index:
                raise PlanError(f"scene {scene.order}: shot order must be 1..N without gaps")
            if shot.end_s <= shot.start_s:
                raise PlanError(f"scene {scene.order}: shot {shot.order} has an empty duration")
            if shot.start_s + 0.01 < previous_shot_end:
                raise PlanError(f"scene {scene.order}: shot {shot.order} overlaps a shot")
            if shot.start_s + 0.01 < scene.start_s or shot.end_s - 0.01 > scene.end_s:
                raise PlanError(f"scene {scene.order}: shot {shot.order} is outside the scene")
            previous_shot_end = shot.end_s
            if not shot.prompt.strip():
                raise PlanError(f"scene {scene.order}: shot {shot.order} has an empty prompt")
            if len(shot.prompt) > MAX_PROMPT:
                raise PlanError(f"scene {scene.order}: shot {shot.order} prompt is too long")
            if len(shot.action) > MAX_TEXT:
                raise PlanError(f"scene {scene.order}: shot {shot.order} action is too long")
            if shot.framing not in CAMERA_FRAMINGS:
                raise PlanError(f"scene {scene.order}: invalid framing {shot.framing!r}")
            if shot.camera_movement not in CAMERA_MOVEMENTS:
                raise PlanError(
                    f"scene {scene.order}: invalid camera_movement {shot.camera_movement!r}"
                )

    for note in payload.notes:
        if not isinstance(note, str):
            raise PlanError("notes must be strings")
        if len(note) > MAX_TEXT:
            raise PlanError(f"note exceeds {MAX_TEXT} characters")

    return payload.model_dump()


def build_prompt(
    *,
    title: str,
    brief: str,
    timeline: dict[str, Any],
    characters: list[str],
    locations: list[str],
    props: list[str],
) -> str:
    sections = [
        {
            "section_index": index,
            "start_s": section.get("start_s"),
            "end_s": section.get("end_s"),
            "energy_tier": section.get("energy_tier"),
        }
        for index, section in enumerate(timeline.get("sections") or [])
        if isinstance(section, dict)
    ]
    bpm = timeline.get("bpm")
    bpm_text = (
        f"{bpm} BPM (confidence {timeline.get('bpm_confidence', 0)})"
        if bpm is not None
        else "BPM not detected, use sections only"
    )
    return _PLAN_PROMPT.format(
        title=title or "(untitled)",
        brief=brief or "(not specified)",
        duration_s=timeline.get("duration_s", 0),
        bpm=bpm_text,
        sections=json.dumps(sections, ensure_ascii=False, indent=2),
        characters=", ".join(characters) or "(none)",
        locations=", ".join(locations) or "(none)",
        props=", ".join(props) or "(none)",
        min_shots=1,
        max_shots=MAX_SHOTS_PER_SCENE,
    )


def _call_ollama(prompt: str, settings: Any) -> str:
    url = f"{settings.ollama_base_url.rstrip('/')}/api/generate"
    payload = {
        "model": settings.planner_model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0},
    }
    with httpx.Client(timeout=settings.planner_timeout_s) as client:
        response = client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
    text = data.get("response")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("модель вернула пустой ответ")
    return text


def merge_response(
    raw: str,
    skeleton: dict[str, Any],
    downbeats: list[float],
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Переносит текст модели в каркас: тайминги и порядок остаются серверными."""

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise PlanError(f"ответ модели не JSON: {error}") from error
    if not isinstance(payload, dict):
        raise PlanError("ответ модели должен быть JSON-объектом")
    candidates = payload.get("scenes")
    if not isinstance(candidates, list):
        raise PlanError("в ответе модели нет списка scenes")

    warnings: list[dict[str, str]] = []
    by_index: dict[int, dict[str, Any]] = {}
    for position, item in enumerate(candidates):
        if not isinstance(item, dict):
            continue
        raw_index = item.get("section_index")
        index = raw_index if isinstance(raw_index, int) and not isinstance(raw_index, bool) else position
        if 0 <= index < len(skeleton["scenes"]):
            by_index.setdefault(index, item)
        else:
            warnings.append(
                {
                    "code": "plan_section_ignored",
                    "message": f"Сцена с section_index={index} отброшена: в таймлайне нет такой секции.",
                }
            )

    defaulted = 0
    scenes: list[dict[str, Any]] = []
    for scene in skeleton["scenes"]:
        candidate = by_index.get(scene["section_index"])
        if candidate is None:
            defaulted += 1
            scenes.append(scene)
            continue

        title = _text(candidate.get("title"), MAX_TITLE)
        raw_shots = candidate.get("shots")
        raw_shots = (
            [item for item in raw_shots if isinstance(item, dict)]
            if isinstance(raw_shots, list)
            else []
        )
        count = max(1, min(MAX_SHOTS_PER_SCENE, len(raw_shots) or len(scene["shots"])))
        timings = _split_shots(
            scene["start_s"], scene["end_s"], downbeats, count, scene["energy_tier"]
        )
        padded = raw_shots[:count] + [{} for _ in range(count - len(raw_shots[:count]))]
        shots: list[dict[str, Any]] = []
        for timing, raw_shot in zip(timings, padded):
            shots.append(
                {
                    "order": timing["order"],
                    "start_s": timing["start_s"],
                    "end_s": timing["end_s"],
                    "action": _text(raw_shot.get("action"), MAX_TEXT),
                    "prompt": _text(raw_shot.get("prompt"), MAX_PROMPT) or timing["prompt"],
                    "framing": _choice(
                        raw_shot.get("framing"), CAMERA_FRAMINGS, timing["framing"]
                    ),
                    "camera_movement": _choice(
                        raw_shot.get("camera_movement"),
                        CAMERA_MOVEMENTS,
                        timing["camera_movement"],
                    ),
                }
            )

        scenes.append(
            {
                "order": scene["order"],
                "section_index": scene["section_index"],
                "title": title or scene["title"],
                "intent": _text(candidate.get("intent"), MAX_TEXT),
                "energy_tier": scene["energy_tier"],
                "start_s": scene["start_s"],
                "end_s": scene["end_s"],
                "shots": shots,
            }
        )

    if defaulted:
        warnings.append(
            {
                "code": "plan_scene_defaulted",
                "message": f"Модель не описала {defaulted} секц. — оставлен каркас, нужна проверка.",
            }
        )

    notes: list[str] = []
    raw_notes = payload.get("notes")
    if isinstance(raw_notes, list):
        for item in raw_notes[:MAX_NOTES]:
            text = _text(item, MAX_TEXT)
            if text:
                notes.append(text)

    plan = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "logline": _text(payload.get("logline"), MAX_TEXT),
        "scenes": scenes,
        "notes": notes,
        "needs_review": bool(defaulted),
    }
    return validate_plan(plan), warnings


def generate_plan(
    *,
    title: str,
    brief: str,
    timeline: dict[str, Any],
    characters: list[str],
    locations: list[str],
    props: list[str],
    settings: Any,
    use_llm: bool = True,
    max_repair: int = MAX_REPAIR_ATTEMPTS,
) -> tuple[dict[str, Any], list[dict[str, str]], str]:
    """Возвращает (план, предупреждения, источник: llm|manual|fallback)."""

    skeleton = build_skeleton(timeline)
    downbeats = [
        float(value) for value in timeline.get("downbeats") or [] if isinstance(value, (int, float))
    ]
    if not use_llm:
        return skeleton, [
            {
                "code": "plan_llm_disabled",
                "message": "Генерация LLM отключена: сохранён детерминированный каркас.",
            }
        ], "manual"

    prompt = build_prompt(
        title=title,
        brief=brief,
        timeline=timeline,
        characters=characters,
        locations=locations,
        props=props,
    )
    warnings: list[dict[str, str]] = []
    for attempt in range(max_repair + 1):
        try:
            raw = _call_ollama(prompt, settings)
        except (httpx.HTTPError, ValueError, KeyError) as error:
            warnings.append(
                {
                    "code": "plan_model_unavailable",
                    "message": f"LLM недоступен ({error}); сохранён детерминированный каркас.",
                }
            )
            return skeleton, warnings, "fallback"
        try:
            plan, merge_warnings = merge_response(raw, skeleton, downbeats)
        except PlanError as error:
            if attempt >= max_repair:
                warnings.append(
                    {
                        "code": "plan_invalid",
                        "message": f"План не прошёл проверку после {max_repair} repair: {error}",
                    }
                )
                return skeleton, warnings, "fallback"
            warnings.append(
                {
                    "code": "plan_repair",
                    "message": f"Попытка {attempt + 1} отклонена: {error}",
                }
            )
            prompt = (
                f"{prompt}\n\nYour previous answer was rejected: {error}\n"
                "Return corrected STRICT JSON only, same schema."
            )
            continue
        warnings.extend(merge_warnings)
        return plan, warnings, "llm"

    return skeleton, warnings, "fallback"
