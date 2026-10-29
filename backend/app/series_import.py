from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.image_probe import ImageProbeError, probe_image
from app.models import Episode, Project, PromptRevision, ReferenceAsset, Shot, ShotReference
from app.models import Scene as SceneRow
from app.series_manifest import DEFAULT_TIMELINE_FPS, SeriesManifest
from app.storage import BlobStore, sha256_file

CREATE = "create"
EXISTS = "exists"
SKIP = "skip"
ERROR = "error"

IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg"})

CATEGORY_LABELS = {
    "project": "Проект",
    "episode": "Эпизод",
    "scene": "Сцена",
    "reference": "Референс",
    "shot": "Шот",
    "prompt": "Промпт",
    "shot_reference": "Связь референса",
}


@dataclass
class ImportOptions:
    project_title: str | None = None
    create_project: bool = False
    reference_dirs: tuple[Path, ...] = ()
    fps: int = DEFAULT_TIMELINE_FPS


@dataclass
class ImportRow:
    category: str
    action: str
    label: str
    detail: str = ""


@dataclass
class ImportReport:
    mode: str
    rows: list[ImportRow] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    project_id: uuid.UUID | None = None
    episode_id: uuid.UUID | None = None
    scene_id: uuid.UUID | None = None
    shots_created: int = 0
    shots_existing: int = 0

    def counts(self) -> dict[str, dict[str, int]]:
        result: dict[str, dict[str, int]] = {}
        for row in self.rows:
            bucket = result.setdefault(
                row.category, {CREATE: 0, EXISTS: 0, SKIP: 0, ERROR: 0}
            )
            bucket[row.action] = bucket.get(row.action, 0) + 1
        return result

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "project_id": str(self.project_id) if self.project_id else None,
            "episode_id": str(self.episode_id) if self.episode_id else None,
            "scene_id": str(self.scene_id) if self.scene_id else None,
            "shots_created": self.shots_created,
            "shots_existing": self.shots_existing,
            "counts": self.counts(),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "rows": [
                {
                    "category": row.category,
                    "action": row.action,
                    "label": row.label,
                    "detail": row.detail,
                }
                for row in self.rows
            ],
        }


def render_report(report: ImportReport) -> str:
    lines = [
        "# Импорт производственного плана",
        "",
        f"- Режим: `{report.mode}`",
        f"- Проект: `{report.project_id}`" if report.project_id else "- Проект: —",
        f"- Эпизод: `{report.episode_id}`" if report.episode_id else "- Эпизод: —",
        f"- Сцена: `{report.scene_id}`" if report.scene_id else "- Сцена: —",
        f"- Шотов создано: {report.shots_created}, уже было: {report.shots_existing}",
        "",
    ]
    for category, bucket in report.counts().items():
        label = CATEGORY_LABELS.get(category, category)
        lines.append(
            f"- {label}: создано {bucket[CREATE]}, уже было {bucket[EXISTS]}, "
            f"пропущено {bucket[SKIP]}, ошибок {bucket[ERROR]}"
        )
    if report.warnings:
        lines += ["", "## Предупреждения", ""]
        lines += [f"- {item}" for item in report.warnings]
    if report.errors:
        lines += ["", "## Ошибки", ""]
        lines += [f"- {item}" for item in report.errors]
    lines += ["", "## Детали", "", "| Объект | Действие | Метка | Детали |", "| --- | --- | --- | --- |"]
    for row in report.rows:
        detail = row.detail.replace("|", "\\|")
        lines.append(
            f"| {CATEGORY_LABELS.get(row.category, row.category)} | {row.action} | "
            f"{row.label} | {detail} |"
        )
    return "\n".join(lines) + "\n"


def asset_names(asset: ReferenceAsset) -> set[str]:
    """Имена, по которым манифест может ссылаться на референс.

    Совпадение имени — только повод проверить файл: принадлежность проекту,
    наличие блоба и sha256 проверяются отдельно.
    """

    names: set[str] = set()
    meta = asset.metadata_json or {}
    for key in ("original_name", "legacy_path"):
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            names.add(Path(value).name)
            names.add(value)
    names.add(PurePosixPath(asset.storage_key).name)
    return names


class SeriesImport:
    """Идемпотентный импорт манифеста в существующие сущности Mary Studio."""

    def __init__(
        self,
        session: Session,
        store: BlobStore,
        manifest: SeriesManifest,
        options: ImportOptions,
        *,
        apply: bool,
        project: Project | None = None,
    ) -> None:
        self.session = session
        self.store = store
        self.manifest = manifest
        self.options = options
        self.apply = apply
        self.project = project
        self.report = ImportReport(mode="apply" if apply else "dry-run")
        self.fps = manifest.effective_fps(options.fps)
        self._digest_cache: dict[uuid.UUID, str | None] = {}
        self._resolved: dict[str, ReferenceAsset | None] = {}

    # --- общие помощники ----------------------------------------------------

    def _record(
        self,
        category: str,
        action: str,
        label: str,
        detail: str = "",
    ) -> None:
        self.report.rows.append(ImportRow(category, action, label, detail))

    def _error(self, category: str, label: str, detail: str) -> None:
        self._record(category, ERROR, label, detail)
        self.report.errors.append(f"{label}: {detail}")

    def _warn(self, message: str) -> None:
        self.report.warnings.append(message)

    # --- запуск -------------------------------------------------------------

    def run(self) -> ImportReport:
        if not self._resolve_project():
            return self.report
        episode = self._resolve_episode()
        scene = self._resolve_scene(episode)
        self.report.scene_id = scene.id
        self._resolve_references()
        for shot in self.manifest.shots:
            self._import_shot(scene, shot)
        return self.report

    # --- проект / эпизод / сцена -------------------------------------------

    def _resolve_project(self) -> bool:
        title = self.options.project_title or self.manifest.project_title
        project = self.project
        if project is None:
            project = self.session.scalar(select(Project).where(Project.title == title))
        if project is not None:
            self.project = project
            self.report.project_id = project.id
            self._record("project", EXISTS, f"«{title}»", f"id={project.id}")
            return True
        if not self.options.create_project:
            self._error(
                "project",
                f"«{title}»",
                "проект не найден; используйте --create-project, чтобы создать его",
            )
            return False
        project = Project(id=uuid.uuid4(), title=title, status="draft")
        self.session.add(project)
        self.session.flush()
        self.project = project
        self.report.project_id = project.id
        self._record("project", CREATE, f"«{title}»", "status='draft'")
        return True

    def _resolve_episode(self) -> Episode:
        assert self.project is not None
        title = self.manifest.episode_title
        episode = self.session.scalar(
            select(Episode)
            .where(Episode.project_id == self.project.id, Episode.title == title)
            .order_by(Episode.sequence_no)
        )
        if episode is not None:
            self.report.episode_id = episode.id
            self._record(
                "episode", EXISTS, title, f"sequence_no={episode.sequence_no}, id={episode.id}"
            )
            return episode
        sequence = (
            self.session.scalar(
                select(func.max(Episode.sequence_no)).where(
                    Episode.project_id == self.project.id
                )
            )
            or 0
        ) + 1
        episode = Episode(
            id=uuid.uuid4(),
            project_id=self.project.id,
            sequence_no=sequence,
            title=title,
            status="draft",
        )
        self.session.add(episode)
        self.session.flush()
        self.report.episode_id = episode.id
        self._record("episode", CREATE, title, f"sequence_no={sequence}, status='draft'")
        return episode

    def _resolve_scene(self, episode: Episode) -> SceneRow:
        assert self.project is not None
        title = self.manifest.episode_title
        scene = self.session.scalar(
            select(SceneRow)
            .where(
                SceneRow.project_id == self.project.id,
                SceneRow.episode_id == episode.id,
                SceneRow.title == title,
            )
            .order_by(SceneRow.sequence_no)
        )
        if scene is not None:
            self._record("scene", EXISTS, title, f"id={scene.id}")
            return scene
        sequence = (
            self.session.scalar(
                select(func.max(SceneRow.sequence_no)).where(
                    SceneRow.project_id == self.project.id
                )
            )
            or 0
        ) + 1
        scene = SceneRow(
            id=uuid.uuid4(),
            project_id=self.project.id,
            episode_id=episode.id,
            sequence_no=sequence,
            title=title,
        )
        self.session.add(scene)
        self.session.flush()
        self._record("scene", CREATE, title, f"sequence_no={sequence}")
        return scene

    # --- референсы ----------------------------------------------------------

    def _name_index(self) -> dict[str, list[ReferenceAsset]]:
        assert self.project is not None
        index: dict[str, list[ReferenceAsset]] = {}
        assets = self.session.scalars(
            select(ReferenceAsset)
            .where(ReferenceAsset.project_id == self.project.id)
            .order_by(ReferenceAsset.created_at)
        )
        for asset in assets:
            for name in asset_names(asset):
                index.setdefault(name, []).append(asset)
        return index

    def _stored_digest(self, asset: ReferenceAsset) -> str | None:
        """sha256 фактического файла в storage; None, если файла нет."""

        cached = self._digest_cache.get(asset.id, ...)
        if cached is not ...:
            return cached
        try:
            path = self.store.resolve(asset.storage_key)
        except Exception:
            self._digest_cache[asset.id] = None
            return None
        digest = sha256_file(path) if path.is_file() else None
        self._digest_cache[asset.id] = digest
        return digest

    def _pick_candidate(
        self, name: str, candidates: list[ReferenceAsset]
    ) -> ReferenceAsset | None:
        """Отбирает референс, у которого файл на месте и совпадает по sha256."""

        verified: list[ReferenceAsset] = []
        for asset in candidates:
            if asset.project_id != self.project.id:  # защита от чужих проектов
                continue
            digest = self._stored_digest(asset)
            if digest is None:
                self._warn(f"{name}: файл референса отсутствует в storage — не используется")
                continue
            if digest != asset.sha256:
                self._warn(
                    f"{name}: sha256 файла не совпадает с записью референса — не используется"
                )
                continue
            verified.append(asset)
        if len(verified) == 1:
            return verified[0]
        if len(verified) > 1:
            self._error(
                "reference",
                name,
                f"несколько подходящих референсов: {', '.join(str(item.id) for item in verified)}",
            )
        return None

    def _find_file(self, name: str) -> Path | None:
        for directory in self.options.reference_dirs:
            candidate = Path(directory) / name
            if candidate.is_file() and candidate.suffix.lower() in IMAGE_SUFFIXES:
                return candidate
        return None

    def _upload_reference(self, name: str, path: Path) -> ReferenceAsset | None:
        assert self.project is not None
        try:
            info = probe_image(path)
        except ImageProbeError as error:
            self._error("reference", name, f"не удалось прочитать файл {path}: {error}")
            return None
        digest = sha256_file(path)
        same_blob = self.session.scalar(
            select(ReferenceAsset).where(
                ReferenceAsset.project_id == self.project.id,
                ReferenceAsset.sha256 == digest,
            )
        )
        if same_blob is not None:
            self._warn(
                f"{name}: файл совпал по sha256 с существующим референсом "
                f"({same_blob.id}) — используется он, имя в манифесте не совпадает"
            )
            return same_blob

        suffix = path.suffix.lower()
        asset = ReferenceAsset(
            id=uuid.uuid4(),
            project_id=self.project.id,
            kind="uploaded",
            status="draft",
            role=path.stem,
            storage_key=self.store.key_for(digest, suffix),
            sha256=digest,
            width=info.width,
            height=info.height,
            mime_type=info.mime_type,
            metadata_json={
                "original_name": name,
                "source": "series_import",
                "has_alpha": info.has_alpha,
            },
        )
        self.session.add(asset)
        if self.apply:
            blob = self.store.put_file(path, suffix=suffix)
            if blob.sha256 != digest:
                self._error("reference", name, "sha256 изменился во время записи в storage")
                return None
        self.session.flush()
        self._record(
            "reference",
            CREATE,
            name,
            f"{info.width}x{info.height}, {info.mime_type}, source='series_import'",
        )
        return asset

    def _resolve_references(self) -> None:
        index = self._name_index()
        for name in self.manifest.reference_names:
            candidates = index.get(name, [])
            asset = self._pick_candidate(name, candidates) if candidates else None
            if asset is None:
                path = self._find_file(name)
                if path is not None:
                    asset = self._upload_reference(name, path)
                elif candidates:
                    self._error(
                        "reference",
                        name,
                        f"в библиотеке {len(candidates)} совпадений по имени, но ни одно "
                        "не прошло проверку файла и sha256",
                    )
                else:
                    self._error(
                        "reference",
                        name,
                        "референс не найден ни в библиотеке, ни в --references-dir; "
                        "фиктивная подстановка запрещена",
                    )
            if asset is not None:
                if candidates:
                    self._record(
                        "reference",
                        EXISTS,
                        name,
                        f"id={asset.id}, status={asset.status}",
                    )
                self._resolved[name] = asset

    # --- шоты ---------------------------------------------------------------

    def _import_shot(self, scene: SceneRow, shot_data: Any) -> None:
        label = f"{shot_data.order:02d} {shot_data.shot_key}"
        shot = self.session.scalar(
            select(Shot).where(
                Shot.scene_id == scene.id, Shot.sequence_no == shot_data.order
            )
        )
        created = shot is None
        if shot is None:
            shot = Shot(
                id=uuid.uuid4(),
                scene_id=scene.id,
                sequence_no=shot_data.order,
                status="draft",
            )
            self.session.add(shot)
            self.session.flush()
            self.report.shots_created += 1
        else:
            self.report.shots_existing += 1

        shot.target_duration_frames = shot_data.frames(self.fps)
        shot.timeline_fps = Decimal(self.fps)
        if shot.status == "draft":
            shot.status = "prompt_ready"
        self._record(
            "shot",
            CREATE if created else EXISTS,
            label,
            f"{shot_data.title}; frames={shot.target_duration_frames}, fps={self.fps}",
        )

        revision = self._import_prompt(shot, shot_data, label)
        if revision is not None and shot.current_prompt_revision_id != revision.id:
            shot.current_prompt_revision_id = revision.id

        self._link_reference(shot, shot_data, label, shot_data.reference_filename)
        self._link_reference(shot, shot_data, label, shot_data.identity_reference_filename)

    def _import_prompt(
        self, shot: Shot, shot_data: Any, label: str
    ) -> PromptRevision | None:
        revisions = list(
            self.session.scalars(
                select(PromptRevision)
                .where(
                    PromptRevision.shot_id == shot.id,
                    PromptRevision.prompt_type == "motion",
                )
                .order_by(PromptRevision.version)
            )
        )
        latest = revisions[-1] if revisions else None
        if latest is not None and latest.prompt == shot_data.prompt_original:
            self._record("prompt", EXISTS, label, f"motion v{latest.version} без изменений")
            return latest

        version = (latest.version + 1) if latest is not None else 1
        parameters = {
            "source": "nine_lives_band_manifest",
            "manifest_sha256": self.manifest.sha256,
            "manifest_source_document": self.manifest.source_document,
            "shot_key": shot_data.shot_key,
            "order": shot_data.order,
            "category": shot_data.category,
            "manifest_status": shot_data.status,
            "output_name_prefix": shot_data.output_name_prefix,
            "duration_seconds": list(shot_data.duration_seconds),
            "timeline_fps": self.fps,
            "target_frames": shot_data.frames(self.fps),
            "target_aspect_ratio": self.manifest.target_aspect_ratio,
            "reference_filename": shot_data.reference_filename,
            "start_frame_filename": shot_data.start_frame_filename,
            "identity_reference_filename": shot_data.identity_reference_filename,
            "seed": shot_data.seed,
            "generator": self.manifest.generator,
            "workflow_version": shot_data.workflow_version,
        }
        revision = PromptRevision(
            id=uuid.uuid4(),
            shot_id=shot.id,
            prompt_type="motion",
            version=version,
            prompt=shot_data.prompt_original,
            parameters_json=parameters,
        )
        self.session.add(revision)
        self.session.flush()
        self._record(
            "prompt",
            CREATE,
            label,
            f"motion v{version}, manifest={self.manifest.sha256[:12]}",
        )
        return revision

    def _link_reference(
        self, shot: Shot, shot_data: Any, label: str, name: str | None
    ) -> None:
        if name is None:
            return
        asset = self._resolved.get(name)
        if asset is None:
            self._record("shot_reference", SKIP, label, f"{name}: референс не разрешён")
            return
        purpose = "location" if shot_data.category == "ensemble" else "character"
        assert self.project is not None
        project_id = self.project.id
        existing = self.session.scalar(
            select(ShotReference).where(
                ShotReference.shot_id == shot.id,
                ShotReference.reference_asset_id == asset.id,
                ShotReference.purpose == purpose,
            )
        )
        if existing is not None:
            self._record(
                "shot_reference", EXISTS, label, f"{purpose}: {name} → {asset.id}"
            )
            return
        self.session.add(
            ShotReference(
                id=uuid.uuid4(),
                project_id=project_id,
                shot_id=shot.id,
                reference_asset_id=asset.id,
                purpose=purpose,
            )
        )
        self.session.flush()
        self._record("shot_reference", CREATE, label, f"{purpose}: {name} → {asset.id}")


def import_series(
    session: Session,
    store: BlobStore,
    manifest: SeriesManifest,
    options: ImportOptions,
    *,
    apply: bool,
    project: Project | None = None,
) -> ImportReport:
    return SeriesImport(
        session, store, manifest, options, apply=apply, project=project
    ).run()
