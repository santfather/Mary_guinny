from __future__ import annotations

import hashlib
import re
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import REPO_ROOT
from app.image_probe import ImageProbeError, guess_mime_type, probe_image
from app.models import (
    Artifact,
    Character,
    CharacterBibleVersion,
    Episode,
    Job,
    Project,
    PromptRevision,
    ReferenceAsset,
    RenderAttempt,
)
from app.models import Scene as SceneRow
from app.models import Shot
from app.storage import BlobStore, sha256_file

CREATE = "create"
EXISTS = "exists"
SKIP = "skip"

IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg"})
SERVICE_FILES = frozenset({".gitkeep", ".DS_Store"})

_KEYFRAME_RE = re.compile(r"^scene_(\d+)_keyframe\.png$", re.IGNORECASE)
_DRAFT_VIDEO_RE = re.compile(r"^scene_(\d+)_draft\.mp4$", re.IGNORECASE)
_SEQUENCE_RE = re.compile(r"(\d+)")

# Семантика имени файла; view/pose/expression ограничены CHECK-ами схемы (WP-02).
_REFERENCE_ATTRIBUTES: dict[str, dict[str, str]] = {
    "front": {"view": "front"},
    "side": {"view": "side"},
    "3q": {"view": "three_quarter"},
    "sit": {"pose": "sit"},
    "walk": {"pose": "walk"},
    "sleep": {"pose": "sleep"},
    "surprised": {"expression": "surprised"},
}

CATEGORY_LABELS = {
    "project": "Проект",
    "character": "Персонаж",
    "bible": "Bible",
    "reference": "Референс",
    "episode": "Эпизод",
    "scene": "Сцена",
    "shot": "Шот",
    "prompt": "Промпт",
    "keyframe": "Ключевой кадр",
    "video": "Черновик видео",
    "file": "Файл",
}

# Порядок вставки: каждая группа ссылается только на предыдущие.
EXECUTION_ORDER = (
    "project",
    "character",
    "bible",
    "reference",
    "episode",
    "scene",
    "shot",
    "prompt",
    "job",
    "attempt",
    "artifact",
)


@dataclass
class Operation:
    category: str
    action: str
    label: str
    detail: str = ""
    entity_kind: str | None = None
    entity: Any | None = None
    source_path: Path | None = None
    suffix: str = ""


@dataclass(frozen=True)
class ImportOptions:
    legacy_root: Path
    storage_root: Path
    project_title: str = "Mary Studio"


@dataclass
class ImportReport:
    mode: str
    legacy_root: Path
    storage_root: Path
    project_title: str
    operations: list[Operation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    blob_writes: int = 0
    blob_hits: int = 0
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None

    def counts(self) -> dict[str, dict[str, int]]:
        result: dict[str, dict[str, int]] = {}
        for operation in self.operations:
            bucket = result.setdefault(
                operation.category, {CREATE: 0, EXISTS: 0, SKIP: 0}
            )
            bucket[operation.action] += 1
        return result

    @property
    def created(self) -> int:
        return sum(1 for operation in self.operations if operation.action == CREATE)


class LegacyImportError(RuntimeError):
    """Импорт нельзя выполнить: отсутствует дерево или нарушена целостность."""


def run_import(
    session: Session, options: ImportOptions, *, apply: bool
) -> ImportReport:
    return LegacyImporter(session, options, apply=apply).run()


class LegacyImporter:
    def __init__(self, session: Session, options: ImportOptions, *, apply: bool) -> None:
        self.session = session
        self.options = options
        self.apply = apply
        self.legacy_root = Path(options.legacy_root).expanduser().resolve()
        self.store = BlobStore(options.storage_root)
        self.operations: list[Operation] = []
        self.warnings: list[str] = []
        self.project: Project | None = None
        # scene_no -> (scene, shot) в рамках текущего эпизода.
        self.scene_index: dict[int, tuple[SceneRow, Shot]] = {}
        # scene_no -> artifact_id ключевого кадра (существующий или запланированный).
        self.keyframe_artifacts: dict[int, uuid.UUID] = {}
        self.blob_writes = 0
        self.blob_hits = 0

    def run(self) -> ImportReport:
        if not self.legacy_root.is_dir():
            raise LegacyImportError(f"legacy root not found: {self.legacy_root}")
        self.project = self._plan_project()
        self._plan_characters()
        self._plan_episodes()
        if self.apply:
            self._execute()
        return ImportReport(
            mode="apply" if self.apply else "dry-run",
            legacy_root=self.legacy_root,
            storage_root=self.store.root,
            project_title=self.options.project_title,
            operations=self.operations,
            warnings=self.warnings,
            blob_writes=self.blob_writes,
            blob_hits=self.blob_hits,
            finished_at=datetime.now(timezone.utc),
        )

    # --- планирование -------------------------------------------------

    def _record(
        self,
        category: str,
        action: str,
        label: str,
        detail: str = "",
        *,
        entity_kind: str | None = None,
        entity: Any | None = None,
        source_path: Path | None = None,
        suffix: str = "",
    ) -> None:
        self.operations.append(
            Operation(
                category=category,
                action=action,
                label=label,
                detail=detail,
                entity_kind=entity_kind,
                entity=entity,
                source_path=source_path,
                suffix=suffix,
            )
        )

    def _plan_project(self) -> Project:
        existing = self.session.scalar(
            select(Project).where(Project.title == self.options.project_title)
        )
        if existing is not None:
            self._record("project", EXISTS, existing.title, f"id={existing.id}")
            return existing
        project = Project(
            id=uuid.uuid4(), title=self.options.project_title, status="active"
        )
        self._record(
            "project",
            CREATE,
            project.title,
            "новый проект (status='active')",
            entity_kind="project",
            entity=project,
        )
        return project

    def _plan_characters(self) -> None:
        root = self.legacy_root / "characters"
        if not root.is_dir():
            self.warnings.append("characters/ не найден — референсы не импортированы")
            return
        for directory in sorted(path for path in root.iterdir() if path.is_dir()):
            self._plan_character(directory)

    def _plan_character(self, directory: Path) -> None:
        assert self.project is not None
        slug = directory.name
        character = self.session.scalar(
            select(Character).where(
                Character.project_id == self.project.id, Character.slug == slug
            )
        )
        if character is None:
            character = Character(
                id=uuid.uuid4(),
                project_id=self.project.id,
                slug=slug,
                name=slug.replace("_", " ").title(),
                kind="other",
                status="draft",
            )
            self._record(
                "character",
                CREATE,
                slug,
                "kind='other' — требует уточнения человеком",
                entity_kind="character",
                entity=character,
            )
            self.warnings.append(
                f"characters/{slug}: kind='other' — семантика персонажа требует "
                "уточнения в библиотеке (S13)"
            )
        else:
            self._record("character", EXISTS, slug, f"id={character.id}")

        self._plan_bible(directory, character)
        self._plan_references(directory, character)

    def _plan_bible(self, directory: Path, character: Character) -> None:
        assert self.project is not None
        path = directory / "character_bible.txt"
        if not path.is_file():
            self.warnings.append(
                f"characters/{directory.name}: character_bible.txt отсутствует"
            )
            return
        body = path.read_text(encoding="utf-8").strip()
        if not body:
            self.warnings.append(
                f"characters/{directory.name}: character_bible.txt пуст"
            )
            return
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        existing = self.session.scalar(
            select(CharacterBibleVersion).where(
                CharacterBibleVersion.character_id == character.id,
                CharacterBibleVersion.sha256 == digest,
            )
        )
        if existing is not None:
            self._record(
                "bible", EXISTS, f"{character.slug} v{existing.version}", digest[:12]
            )
            return
        current = self.session.scalar(
            select(func.max(CharacterBibleVersion.version)).where(
                CharacterBibleVersion.character_id == character.id
            )
        )
        version = (current or 0) + 1
        row = CharacterBibleVersion(
            id=uuid.uuid4(),
            project_id=self.project.id,
            character_id=character.id,
            version=version,
            body=body,
            sha256=digest,
            status="draft",
            source="import",
        )
        self._record(
            "bible",
            CREATE,
            f"{character.slug} v{version}",
            f"draft, source='import', sha256={digest[:12]}",
            entity_kind="bible",
            entity=row,
        )

    def _plan_references(self, directory: Path, character: Character) -> None:
        for path in sorted(directory.iterdir()):
            if not path.is_file() or path.name in SERVICE_FILES:
                continue
            if path.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            relative = path.relative_to(self.legacy_root).as_posix()
            if not path.name.startswith("reference_"):
                self._record(
                    "reference",
                    SKIP,
                    relative,
                    "имя не соответствует reference_*; автоматический импорт не выполняется",
                )
                self.warnings.append(
                    f"{relative}: файл не импортирован автоматически — требуется решение человека"
                )
                continue
            self._plan_reference(path, character, relative)

    def _plan_reference(
        self, path: Path, character: Character, relative: str
    ) -> None:
        assert self.project is not None
        try:
            info = probe_image(path)
        except ImageProbeError as error:
            self._record("reference", SKIP, relative, f"не удалось прочитать изображение: {error}")
            self.warnings.append(f"{relative}: {error}")
            return
        digest = sha256_file(path)
        existing = self.session.scalar(
            select(ReferenceAsset).where(
                ReferenceAsset.project_id == self.project.id,
                ReferenceAsset.sha256 == digest,
            )
        )
        if existing is not None:
            self._record("reference", EXISTS, relative, f"sha256={digest[:12]}, id={existing.id}")
            return

        attributes = _reference_attributes(path.stem)
        suffix = path.suffix.lower()
        asset = ReferenceAsset(
            id=uuid.uuid4(),
            project_id=self.project.id,
            kind="character_reference",
            character_id=character.id,
            status="draft",
            role=path.stem,
            view=attributes.get("view"),
            pose=attributes.get("pose"),
            expression=attributes.get("expression"),
            storage_key=self.store.key_for(digest, suffix),
            sha256=digest,
            width=info.width,
            height=info.height,
            mime_type=info.mime_type,
            metadata_json={"legacy_path": relative, "has_alpha": info.has_alpha},
        )
        self._record(
            "reference",
            CREATE,
            relative,
            f"{info.width}x{info.height}, {info.mime_type}, "
            f"alpha={'да' if info.has_alpha else 'нет'}, view={asset.view}, "
            f"pose={asset.pose}, expression={asset.expression}",
            entity_kind="reference",
            entity=asset,
            source_path=path,
            suffix=suffix,
        )
        if not info.has_alpha:
            self.warnings.append(
                f"{relative}: нет альфа-канала — непрозрачный референс, "
                "проверить при композиции"
            )

    def _plan_episodes(self) -> None:
        root = self.legacy_root / "episodes"
        if not root.is_dir():
            self.warnings.append("episodes/ не найден — эпизоды не импортированы")
            return
        for directory in sorted(path for path in root.iterdir() if path.is_dir()):
            self._plan_episode(directory)

    def _plan_episode(self, directory: Path) -> None:
        assert self.project is not None
        name = directory.name
        sequence = _sequence_from_name(name)
        if sequence is None:
            self._record(
                "episode", SKIP, name, "не удалось определить номер эпизода из имени каталога"
            )
            self.warnings.append(f"episodes/{name}: номер эпизода не определён")
            return
        script_path = directory / "script.txt"
        if not script_path.is_file():
            self._record("episode", SKIP, name, "нет script.txt — эпизод не импортирован")
            self.warnings.append(f"episodes/{name}: script.txt отсутствует")
            self._plan_episode_skips(directory)
            return

        episode = self.session.scalar(
            select(Episode).where(
                Episode.project_id == self.project.id, Episode.sequence_no == sequence
            )
        )
        if episode is None:
            episode = Episode(
                id=uuid.uuid4(),
                project_id=self.project.id,
                sequence_no=sequence,
                title=name,
                status="draft",
            )
            self._record(
                "episode",
                CREATE,
                name,
                f"sequence_no={sequence}, status='draft'",
                entity_kind="episode",
                entity=episode,
            )
        else:
            self._record("episode", EXISTS, name, f"id={episode.id}")

        text = script_path.read_text(encoding="utf-8")
        try:
            parsed_scenes = _parse_script(text)
        except Exception as error:  # legacy-парсер — внешний контракт
            self._record("episode", SKIP, name, f"ошибка разбора script.txt: {error}")
            self.warnings.append(f"episodes/{name}/script.txt: {error}")
            return
        if not parsed_scenes:
            self.warnings.append(f"episodes/{name}/script.txt: сцены не найдены")

        self.scene_index = {}
        self.keyframe_artifacts = {}
        for parsed in parsed_scenes:
            self._plan_scene(episode, parsed, script_path)
        self._plan_episode_files(directory)

    def _plan_scene(self, episode: Episode, parsed: Any, script_path: Path) -> None:
        assert self.project is not None
        scene = self.session.scalar(
            select(SceneRow).where(
                SceneRow.project_id == self.project.id,
                SceneRow.episode_id == episode.id,
                SceneRow.sequence_no == parsed.number,
            )
        )
        if scene is None:
            scene = SceneRow(
                id=uuid.uuid4(),
                project_id=self.project.id,
                episode_id=episode.id,
                sequence_no=parsed.number,
                title=parsed.title or None,
            )
            self._record(
                "scene",
                CREATE,
                f"episode {episode.sequence_no} / scene {parsed.number}",
                parsed.title or "",
                entity_kind="scene",
                entity=scene,
            )
        else:
            self._record(
                "scene", EXISTS, f"episode {episode.sequence_no} / scene {parsed.number}", f"id={scene.id}"
            )

        shot = self.session.scalar(
            select(Shot).where(Shot.scene_id == scene.id, Shot.sequence_no == 1)
        )
        if shot is None:
            shot = Shot(id=uuid.uuid4(), scene_id=scene.id, sequence_no=1, status="draft")
            self._record(
                "shot",
                CREATE,
                f"episode {episode.sequence_no} / scene {parsed.number} / shot 1",
                "status='draft'",
                entity_kind="shot",
                entity=shot,
            )
        else:
            self._record(
                "shot",
                EXISTS,
                f"episode {episode.sequence_no} / scene {parsed.number} / shot 1",
                f"id={shot.id}",
            )

        prompt_text = parsed.raw_block.strip()
        prompt = self.session.scalar(
            select(PromptRevision).where(
                PromptRevision.shot_id == shot.id,
                PromptRevision.prompt_type == "script",
                PromptRevision.version == 1,
            )
        )
        if prompt is None:
            prompt = PromptRevision(
                id=uuid.uuid4(),
                shot_id=shot.id,
                prompt_type="script",
                version=1,
                prompt=prompt_text,
                parameters_json={
                    "episode": episode.sequence_no,
                    "scene": parsed.number,
                    "title": parsed.title or None,
                    "legacy_script": script_path.relative_to(self.legacy_root).as_posix(),
                },
            )
            self._record(
                "prompt",
                CREATE,
                f"episode {episode.sequence_no} / scene {parsed.number}",
                "prompt_type='script', version=1",
                entity_kind="prompt",
                entity=prompt,
            )
        else:
            self._record(
                "prompt", EXISTS, f"episode {episode.sequence_no} / scene {parsed.number}", f"id={prompt.id}"
            )
        self.scene_index[parsed.number] = (scene, shot)

    def _plan_episode_files(self, directory: Path) -> None:
        self._plan_episode_skips(directory)
        scenes_dir = directory / "scenes"
        if not scenes_dir.is_dir():
            return
        files = [
            path
            for path in sorted(scenes_dir.iterdir())
            if path.is_file() and path.name not in SERVICE_FILES
        ]
        # Сначала ключевые кадры: видео ссылается на стартовый кадр как input.
        for path in files:
            keyframe = _KEYFRAME_RE.match(path.name)
            if keyframe:
                relative = path.relative_to(self.legacy_root).as_posix()
                self._plan_keyframe(path, int(keyframe.group(1)), relative)
        for path in files:
            if _KEYFRAME_RE.match(path.name):
                continue
            relative = path.relative_to(self.legacy_root).as_posix()
            draft_video = _DRAFT_VIDEO_RE.match(path.name)
            if draft_video:
                self._plan_draft_video(path, int(draft_video.group(1)), relative)
                continue
            self._record(
                "file",
                SKIP,
                relative,
                "вне MVP: импортируются только *_keyframe.png и *_draft.mp4",
            )

    def _plan_episode_skips(self, directory: Path) -> None:
        for subdir, reason in (
            ("audio", "аудио — post-MVP, импорт не выполняется"),
            ("poc", "POC-эксперимент — вне MVP"),
        ):
            path = directory / subdir
            if not path.is_dir():
                continue
            for file in sorted(path.iterdir()):
                if not file.is_file() or file.name in SERVICE_FILES:
                    continue
                self._record(
                    "file", SKIP, file.relative_to(self.legacy_root).as_posix(), reason
                )

    def _plan_keyframe(self, path: Path, scene_number: int, relative: str) -> None:
        scene_entry = self.scene_index.get(scene_number)
        if scene_entry is None:
            self._record(
                "keyframe", SKIP, relative, f"сцена {scene_number} не найдена в script.txt"
            )
            self.warnings.append(f"{relative}: сцена {scene_number} отсутствует в сценарии")
            return
        _, shot = scene_entry
        digest = sha256_file(path)
        existing = self._existing_artifact_id(shot.id, digest)
        if existing is not None:
            self._record("keyframe", EXISTS, relative, f"artifact={existing}")
            self.keyframe_artifacts[scene_number] = existing
            return
        try:
            info = probe_image(path)
        except ImageProbeError as error:
            self._record("keyframe", SKIP, relative, str(error))
            self.warnings.append(f"{relative}: {error}")
            return

        attempt = RenderAttempt(
            id=uuid.uuid4(),
            shot_id=shot.id,
            job_id=None,
            kind="keyframe",
            status="completed",
            parameters={
                "source": "legacy-import",
                "legacy_path": relative,
                "sha256": digest,
                "width": info.width,
                "height": info.height,
                "has_alpha": info.has_alpha,
            },
        )
        artifact = Artifact(
            id=uuid.uuid4(),
            attempt_id=attempt.id,
            source="attempt",
            kind="keyframe",
            storage_key=self.store.key_for(digest, path.suffix.lower()),
            sha256=digest,
            bytes=path.stat().st_size,
            mime_type=info.mime_type,
        )
        self._record(
            "keyframe",
            CREATE,
            relative,
            f"{info.width}x{info.height}, {info.mime_type}, "
            f"alpha={'да' if info.has_alpha else 'нет'}",
            entity_kind="attempt",
            entity=attempt,
            source_path=path,
            suffix=path.suffix.lower(),
        )
        self._record(
            "keyframe",
            CREATE,
            relative,
            f"artifact kind='keyframe', sha256={digest[:12]}",
            entity_kind="artifact",
            entity=artifact,
        )
        self.keyframe_artifacts[scene_number] = artifact.id
        if not info.has_alpha:
            self.warnings.append(f"{relative}: нет альфа-канала — непрозрачный кадр")

    def _plan_draft_video(self, path: Path, scene_number: int, relative: str) -> None:
        scene_entry = self.scene_index.get(scene_number)
        if scene_entry is None:
            self._record(
                "video", SKIP, relative, f"сцена {scene_number} не найдена в script.txt"
            )
            self.warnings.append(f"{relative}: сцена {scene_number} отсутствует в сценарии")
            return
        _, shot = scene_entry
        digest = sha256_file(path)
        existing = self._existing_artifact_id(shot.id, digest)
        if existing is not None:
            self._record("video", EXISTS, relative, f"artifact={existing}")
            return

        # Схема требует job_id для kind='video' (S12); создаём синтетический
        # completed-job, идемпотентный по sha256 исходного файла.
        idempotency_key = f"legacy:{digest}"
        job = self.session.scalar(
            select(Job).where(Job.idempotency_key == idempotency_key)
        )
        if job is None:
            job = Job(
                id=uuid.uuid4(),
                kind="render_video",
                shot_id=shot.id,
                status="completed",
                idempotency_key=idempotency_key,
                attempts=1,
                payload={"source": "legacy-import", "legacy_path": relative},
            )
            self._record(
                "video",
                CREATE,
                relative,
                f"синтетический job(kind='render_video', status='completed'), "
                f"idempotency_key={idempotency_key[:19]}…",
                entity_kind="job",
                entity=job,
            )
        else:
            self._record("video", EXISTS, relative, f"job={job.id}")

        input_artifact = self.keyframe_artifacts.get(scene_number)
        attempt = RenderAttempt(
            id=uuid.uuid4(),
            shot_id=shot.id,
            job_id=job.id,
            kind="video",
            status="completed",
            input_artifact_ids=[str(input_artifact)] if input_artifact else None,
            parameters={
                "source": "legacy-import",
                "legacy_path": relative,
                "sha256": digest,
            },
        )
        artifact = Artifact(
            id=uuid.uuid4(),
            attempt_id=attempt.id,
            source="attempt",
            kind="video_draft",
            storage_key=self.store.key_for(digest, path.suffix.lower()),
            sha256=digest,
            bytes=path.stat().st_size,
            mime_type=guess_mime_type(path),
        )
        self._record(
            "video",
            CREATE,
            relative,
            "attempt kind='video' + artifact kind='video_draft'",
            entity_kind="attempt",
            entity=attempt,
            source_path=path,
            suffix=path.suffix.lower(),
        )
        self._record(
            "video",
            CREATE,
            relative,
            f"artifact kind='video_draft', sha256={digest[:12]}",
            entity_kind="artifact",
            entity=artifact,
        )

    def _existing_artifact_id(self, shot_id: uuid.UUID, digest: str) -> uuid.UUID | None:
        statement = (
            select(Artifact.id)
            .join(RenderAttempt, RenderAttempt.id == Artifact.attempt_id)
            .where(RenderAttempt.shot_id == shot_id, Artifact.sha256 == digest)
        )
        return self.session.scalar(statement)

    # --- применение ---------------------------------------------------

    def _execute(self) -> None:
        for entity_kind in EXECUTION_ORDER:
            group = [
                operation
                for operation in self.operations
                if operation.entity_kind == entity_kind and operation.action == CREATE
            ]
            if not group:
                continue
            for operation in group:
                if operation.source_path is not None:
                    blob = self.store.put_file(
                        operation.source_path, suffix=operation.suffix
                    )
                    assert operation.entity is not None
                    if getattr(operation.entity, "storage_key", blob.storage_key) != blob.storage_key:
                        raise LegacyImportError(
                            f"storage_key mismatch for {operation.label}: "
                            f"{operation.entity.storage_key} != {blob.storage_key}"
                        )
                    if blob.created:
                        self.blob_writes += 1
                    else:
                        self.blob_hits += 1
                if operation.entity is not None:
                    self.session.add(operation.entity)
            self.session.flush()


def _parse_script(text: str) -> list[Any]:
    """Разбор script.txt legacy-парсером: не дублируем правила в backend."""

    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from pipeline.utils import parse_script

    return parse_script(text)


def _sequence_from_name(name: str) -> int | None:
    match = _SEQUENCE_RE.search(name)
    return int(match.group(1)) if match else None


def _reference_attributes(stem: str) -> dict[str, str]:
    name = stem.lower()
    if name.startswith("reference_"):
        name = name[len("reference_") :]
    return dict(_REFERENCE_ATTRIBUTES.get(name, {}))


def _escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def render_report(report: ImportReport) -> str:
    counts = report.counts()
    lines: list[str] = [
        "# Отчёт миграции legacy-файлов",
        "",
        f"- Режим: `{report.mode}`",
        f"- Legacy root: `{report.legacy_root}`",
        f"- Storage root: `{report.storage_root}`",
        f"- Проект: `{report.project_title}`",
        f"- Начало (UTC): {report.started_at:%Y-%m-%d %H:%M:%S}",
    ]
    if report.finished_at is not None:
        lines.append(f"- Окончание (UTC): {report.finished_at:%Y-%m-%d %H:%M:%S}")
    if report.mode == "apply":
        lines.append(
            f"- Записано новых blob: {report.blob_writes}; "
            f"переиспользовано существующих: {report.blob_hits}"
        )
    lines.extend(["", "## Сводка", "", "| Категория | Создано | Уже есть | Пропущено |", "|---|---|---|---|"])
    for category in CATEGORY_LABELS:
        bucket = counts.get(category)
        if bucket is None:
            continue
        lines.append(
            f"| {CATEGORY_LABELS[category]} | {bucket[CREATE]} | {bucket[EXISTS]} | {bucket[SKIP]} |"
        )

    for action, title in ((CREATE, "Создано"), (EXISTS, "Уже существует")):
        rows = [operation for operation in report.operations if operation.action == action]
        lines.extend(["", f"## {title}", ""])
        if not rows:
            lines.append("Нет записей.")
            continue
        lines.extend(["| Категория | Объект | Детали |", "|---|---|---|"])
        for operation in rows:
            lines.append(
                f"| {CATEGORY_LABELS.get(operation.category, operation.category)} "
                f"| {_escape(operation.label)} | {_escape(operation.detail)} |"
            )

    skipped = [operation for operation in report.operations if operation.action == SKIP]
    lines.extend(["", "## Пропущено", ""])
    if skipped:
        lines.extend(["| Источник | Причина |", "|---|---|"])
        for operation in skipped:
            lines.append(f"| {_escape(operation.label)} | {_escape(operation.detail)} |")
    else:
        lines.append("Нет пропущенных файлов.")

    lines.extend(["", "## Предупреждения", ""])
    if report.warnings:
        lines.extend(f"- {warning}" for warning in report.warnings)
    else:
        lines.append("Нет.")

    lines.extend(
        [
            "",
            "## Оригиналы",
            "",
            "Импорт только читает исходные файлы: ничего не перемещено и не удалено.",
            "Повторный запуск идемпотентен по sha256; дубликаты в БД и storage не создаются.",
            "",
        ]
    )
    return "\n".join(lines)
