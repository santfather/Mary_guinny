from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_session, require_project
from app.api.schemas import ReferenceOut
from app.api.shot_schemas import (
    AttemptOut,
    CompositionSummary,
    KeyframeCreate,
    KeyframeOut,
    RenderQueuedOut,
    SceneCreate,
    SceneOut,
    ShotCreate,
    ShotDetail,
    ShotReferenceCreate,
    ShotReferenceOut,
    ShotSummary,
)
from app.models import (
    Artifact,
    Episode,
    Job,
    RenderAttempt,
    Scene,
    Shot,
    ShotComposition,
    ShotCompositionLayer,
    ShotReference,
    ReferenceAsset,
    VisualScenePlan,
)

router = APIRouter(prefix="/api", tags=["shots"])

ACTIVE_JOB_STATUSES = (
    "pending",
    "leased",
    "running",
    "retry_wait",
    "cancel_requested",
    "lease_expired",
)


def require_scene(session: Session, scene_id: uuid.UUID) -> Scene:
    scene = session.get(Scene, scene_id)
    if scene is None:
        raise HTTPException(status_code=404, detail="scene not found")
    return scene


def require_shot(session: Session, shot_id: uuid.UUID) -> Shot:
    shot = session.get(Shot, shot_id)
    if shot is None:
        raise HTTPException(status_code=404, detail="shot not found")
    return shot


def shot_project_id(session: Session, shot: Shot) -> uuid.UUID:
    project_id = session.scalar(
        select(Scene.project_id).where(Scene.id == shot.scene_id)
    )
    if project_id is None:
        raise HTTPException(status_code=409, detail="shot scene is missing")
    return project_id


def reference_links(session: Session, shot_id: uuid.UUID) -> list[ShotReferenceOut]:
    links = list(
        session.scalars(
            select(ShotReference)
            .where(ShotReference.shot_id == shot_id)
            .order_by(ShotReference.created_at, ShotReference.id)
        )
    )
    if not links:
        return []
    assets = {
        asset.id: asset
        for asset in session.scalars(
            select(ReferenceAsset).where(
                ReferenceAsset.id.in_([link.reference_asset_id for link in links])
            )
        )
    }
    return [
        ShotReferenceOut.from_link(link, ReferenceOut.from_asset(assets[link.reference_asset_id]))
        for link in links
        if link.reference_asset_id in assets
    ]


def layout_mockup_ids(
    session: Session, composition_ids: list[uuid.UUID]
) -> set[uuid.UUID]:
    """Композиции, где непрозрачный персонаж перекрывает фон (layout mockup)."""

    if not composition_ids:
        return set()
    rows = session.execute(
        select(ShotCompositionLayer.composition_id)
        .join(
            ReferenceAsset,
            ReferenceAsset.id == ShotCompositionLayer.reference_asset_id,
        )
        .where(
            ShotCompositionLayer.composition_id.in_(composition_ids),
            ReferenceAsset.kind == "character_reference",
            ReferenceAsset.metadata_json["has_alpha"].astext == "false",
        )
    )
    return {row[0] for row in rows}


def composition_summaries(
    session: Session, shot_id: uuid.UUID
) -> list[CompositionSummary]:
    compositions = list(
        session.scalars(
            select(ShotComposition)
            .where(ShotComposition.shot_id == shot_id)
            .order_by(ShotComposition.revision.desc())
        )
    )
    if not compositions:
        return []
    composition_ids = [composition.id for composition in compositions]
    counts = dict(
        session.execute(
            select(
                ShotCompositionLayer.composition_id, func.count(ShotCompositionLayer.id)
            )
            .where(ShotCompositionLayer.composition_id.in_(composition_ids))
            .group_by(ShotCompositionLayer.composition_id)
        ).all()
    )
    mockups = layout_mockup_ids(session, composition_ids)
    return [
        CompositionSummary.from_composition(
            composition,
            counts.get(composition.id, 0),
            layout_mockup=composition.id in mockups,
        )
        for composition in compositions
    ]


def attempt_outs(session: Session, shot_id: uuid.UUID) -> list[AttemptOut]:
    attempts = list(
        session.scalars(
            select(RenderAttempt)
            .where(RenderAttempt.shot_id == shot_id)
            .order_by(RenderAttempt.created_at.desc())
        )
    )
    if not attempts:
        return []
    artifacts: dict[uuid.UUID, uuid.UUID] = {}
    for artifact in session.scalars(
        select(Artifact)
        .where(Artifact.attempt_id.in_([attempt.id for attempt in attempts]))
        .order_by(Artifact.created_at)
    ):
        if artifact.attempt_id is not None:
            artifacts.setdefault(artifact.attempt_id, artifact.id)
    return [
        AttemptOut.from_attempt(attempt, artifacts.get(attempt.id)) for attempt in attempts
    ]


@router.get("/projects/{project_id}/scenes", response_model=list[SceneOut])
def list_scenes(
    project_id: uuid.UUID, session: Session = Depends(get_session)
) -> list[SceneOut]:
    require_project(session, project_id)
    scenes = list(
        session.scalars(
            select(Scene)
            .where(Scene.project_id == project_id)
            .order_by(Scene.sequence_no, Scene.id)
        )
    )
    grouped: dict[uuid.UUID, list[ShotSummary]] = defaultdict(list)
    for shot in session.scalars(
        select(Shot)
        .join(Scene, Shot.scene_id == Scene.id)
        .where(Scene.project_id == project_id)
        .order_by(Shot.sequence_no, Shot.id)
    ):
        grouped[shot.scene_id].append(ShotSummary.from_shot(shot, project_id))
    return [SceneOut.from_scene(scene, grouped[scene.id]) for scene in scenes]


@router.post(
    "/projects/{project_id}/scenes",
    response_model=SceneOut,
    status_code=status.HTTP_201_CREATED,
)
def create_scene(
    project_id: uuid.UUID,
    payload: SceneCreate,
    session: Session = Depends(get_session),
) -> SceneOut:
    require_project(session, project_id)
    if payload.episode_id is not None:
        episode = session.get(Episode, payload.episode_id)
        if episode is None or episode.project_id != project_id:
            raise HTTPException(status_code=422, detail="episode belongs to another project")

    sequence_no = payload.sequence_no
    if sequence_no is None:
        sequence_no = (
            session.scalar(
                select(func.coalesce(func.max(Scene.sequence_no), 0)).where(
                    Scene.project_id == project_id
                )
            )
            + 1
        )
    scene = Scene(
        project_id=project_id,
        episode_id=payload.episode_id,
        sequence_no=sequence_no,
        title=payload.title,
    )
    session.add(scene)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="scene sequence_no already exists"
        ) from error
    session.refresh(scene)
    return SceneOut.from_scene(scene, [])


@router.get("/scenes/{scene_id}", response_model=SceneOut)
def get_scene(scene_id: uuid.UUID, session: Session = Depends(get_session)) -> SceneOut:
    scene = require_scene(session, scene_id)
    shots = list(
        session.scalars(
            select(Shot)
            .where(Shot.scene_id == scene.id)
            .order_by(Shot.sequence_no, Shot.id)
        )
    )
    return SceneOut.from_scene(
        scene, [ShotSummary.from_shot(shot, scene.project_id) for shot in shots]
    )


@router.post(
    "/scenes/{scene_id}/shots",
    response_model=ShotSummary,
    status_code=status.HTTP_201_CREATED,
)
def create_shot(
    scene_id: uuid.UUID,
    payload: ShotCreate,
    session: Session = Depends(get_session),
) -> ShotSummary:
    scene = require_scene(session, scene_id)
    sequence_no = payload.sequence_no
    if sequence_no is None:
        sequence_no = (
            session.scalar(
                select(func.coalesce(func.max(Shot.sequence_no), 0)).where(
                    Shot.scene_id == scene.id
                )
            )
            + 1
        )
    shot = Shot(
        scene_id=scene.id,
        sequence_no=sequence_no,
        target_duration_frames=payload.target_duration_frames,
        timeline_fps=payload.timeline_fps,
    )
    session.add(shot)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="shot sequence_no already exists"
        ) from error
    session.refresh(shot)
    return ShotSummary.from_shot(shot, scene.project_id)


@router.get("/shots/{shot_id}", response_model=ShotDetail)
def get_shot(shot_id: uuid.UUID, session: Session = Depends(get_session)) -> ShotDetail:
    shot = require_shot(session, shot_id)
    project_id = shot_project_id(session, shot)
    summary = ShotSummary.from_shot(shot, project_id)
    return ShotDetail(
        **summary.model_dump(),
        references=reference_links(session, shot.id),
        composition_revisions=composition_summaries(session, shot.id),
        attempts=attempt_outs(session, shot.id),
    )


@router.get("/shots/{shot_id}/references", response_model=list[ShotReferenceOut])
def list_shot_references(
    shot_id: uuid.UUID, session: Session = Depends(get_session)
) -> list[ShotReferenceOut]:
    require_shot(session, shot_id)
    return reference_links(session, shot_id)


@router.post(
    "/shots/{shot_id}/references",
    response_model=ShotReferenceOut,
    status_code=status.HTTP_201_CREATED,
)
def attach_shot_reference(
    shot_id: uuid.UUID,
    payload: ShotReferenceCreate,
    session: Session = Depends(get_session),
) -> ShotReferenceOut:
    shot = require_shot(session, shot_id)
    project_id = shot_project_id(session, shot)
    asset = session.get(ReferenceAsset, payload.reference_asset_id)
    if asset is None or asset.project_id != project_id:
        raise HTTPException(status_code=404, detail="reference asset not found")
    if asset.status in ("rejected", "superseded"):
        raise HTTPException(
            status_code=409,
            detail=f"cannot attach reference in status '{asset.status}'",
        )

    existing = session.scalar(
        select(ShotReference).where(
            ShotReference.shot_id == shot.id,
            ShotReference.reference_asset_id == asset.id,
            ShotReference.purpose == payload.purpose,
        )
    )
    if existing is not None:
        return ShotReferenceOut.from_link(existing, ReferenceOut.from_asset(asset))

    link = ShotReference(
        project_id=project_id,
        shot_id=shot.id,
        reference_asset_id=asset.id,
        purpose=payload.purpose,
    )
    session.add(link)
    session.commit()
    session.refresh(link)
    return ShotReferenceOut.from_link(link, ReferenceOut.from_asset(asset))


@router.delete(
    "/shots/{shot_id}/references/{link_id}", status_code=status.HTTP_204_NO_CONTENT
)
def detach_shot_reference(
    shot_id: uuid.UUID,
    link_id: uuid.UUID,
    session: Session = Depends(get_session),
) -> None:
    require_shot(session, shot_id)
    link = session.get(ShotReference, link_id)
    if link is None or link.shot_id != shot_id:
        raise HTTPException(status_code=404, detail="shot reference not found")
    session.delete(link)
    session.commit()


@router.get("/shots/{shot_id}/attempts", response_model=list[AttemptOut])
def list_attempts(
    shot_id: uuid.UUID, session: Session = Depends(get_session)
) -> list[AttemptOut]:
    require_shot(session, shot_id)
    return attempt_outs(session, shot_id)


def _keyframe_parameters(
    session: Session, composition: ShotComposition
) -> dict[str, object]:
    parameters: dict[str, object] = {
        "composition_id": str(composition.id),
        "composition_revision": composition.revision,
    }
    if composition.source_plan_id is not None:
        plan = session.get(VisualScenePlan, composition.source_plan_id)
        if plan is not None:
            # Проверяемое происхождение: artifact → attempt → composition → plan.
            parameters["visual_plan_id"] = str(plan.id)
            parameters["visual_plan_revision"] = plan.revision
    return parameters


@router.post(
    "/shots/{shot_id}/keyframe",
    response_model=KeyframeOut,
    status_code=status.HTTP_201_CREATED,
)
def create_keyframe(
    shot_id: uuid.UUID,
    payload: KeyframeCreate,
    session: Session = Depends(get_session),
) -> KeyframeOut:
    shot = require_shot(session, shot_id)
    statement = select(ShotComposition).where(ShotComposition.shot_id == shot.id)
    if payload.composition_revision is not None:
        composition = session.scalar(
            statement.where(ShotComposition.revision == payload.composition_revision)
        )
        if composition is None:
            raise HTTPException(status_code=404, detail="composition revision not found")
    else:
        composition = session.scalar(
            statement.order_by(ShotComposition.revision.desc()).limit(1)
        )
        if composition is None:
            raise HTTPException(
                status_code=409, detail="shot has no composition revisions"
            )

    if composition.status != "approved":
        raise HTTPException(
            status_code=409, detail="composition revision must be approved"
        )
    if composition.preview_artifact_id is None:
        raise HTTPException(
            status_code=409, detail="composition revision has no rendered preview"
        )
    preview = session.get(Artifact, composition.preview_artifact_id)
    if preview is None:
        raise HTTPException(status_code=409, detail="composition preview artifact is missing")

    attempt = RenderAttempt(
        shot_id=shot.id,
        kind="keyframe",
        status="completed",
        input_artifact_ids=[str(preview.id)],
        workflow_version="composition-v1",
        parameters=_keyframe_parameters(session, composition),
    )
    session.add(attempt)
    session.flush()
    artifact = Artifact(
        attempt_id=attempt.id,
        source="attempt",
        kind="keyframe",
        storage_key=preview.storage_key,
        sha256=preview.sha256,
        bytes=preview.bytes,
        mime_type=preview.mime_type,
    )
    session.add(artifact)
    session.commit()
    session.refresh(attempt)
    session.refresh(artifact)
    return KeyframeOut(
        attempt_id=attempt.id,
        artifact_id=artifact.id,
        artifact_content_url=f"/api/artifacts/{artifact.id}/content",
        composition_revision=composition.revision,
        status=attempt.status,
    )


@router.post(
    "/shots/{shot_id}/attempts/{attempt_id}/promote-keyframe",
    response_model=ShotSummary,
)
def promote_keyframe(
    shot_id: uuid.UUID,
    attempt_id: uuid.UUID,
    session: Session = Depends(get_session),
) -> ShotSummary:
    shot = require_shot(session, shot_id)
    attempt = session.get(RenderAttempt, attempt_id)
    if attempt is None or attempt.shot_id != shot.id:
        raise HTTPException(status_code=404, detail="render attempt not found")
    if attempt.kind != "keyframe":
        raise HTTPException(status_code=409, detail="attempt is not a keyframe attempt")
    if attempt.status != "completed":
        raise HTTPException(status_code=409, detail="attempt is not completed")

    artifact = session.scalar(
        select(Artifact)
        .where(Artifact.attempt_id == attempt.id)
        .order_by(Artifact.created_at.desc())
        .limit(1)
    )
    if artifact is None:
        raise HTTPException(status_code=409, detail="keyframe artifact is missing")

    project_id = shot_project_id(session, shot)
    if (
        shot.start_keyframe_artifact_id == artifact.id
        and shot.start_keyframe_attempt_id == attempt.id
    ):
        return ShotSummary.from_shot(shot, project_id)

    shot.start_keyframe_artifact_id = artifact.id
    shot.start_keyframe_attempt_id = attempt.id
    session.commit()
    session.refresh(shot)
    return ShotSummary.from_shot(shot, project_id)


def _queued_out(job: Job, shot: Shot) -> RenderQueuedOut:
    payload = job.payload or {}
    raw = payload.get("start_keyframe_artifact_id")
    artifact_id = uuid.UUID(str(raw)) if raw else shot.start_keyframe_artifact_id
    return RenderQueuedOut(
        job_id=job.id,
        status=job.status,
        shot_id=shot.id,
        start_keyframe_artifact_id=artifact_id,
    )


@router.post(
    "/shots/{shot_id}/render",
    response_model=RenderQueuedOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def queue_render(
    shot_id: uuid.UUID,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    session: Session = Depends(get_session),
) -> RenderQueuedOut:
    shot = require_shot(session, shot_id)
    if shot.start_keyframe_artifact_id is None:
        raise HTTPException(status_code=409, detail="start keyframe is not approved")

    key: str | None = None
    if idempotency_key is not None:
        key = idempotency_key.strip()
        if not key or len(key) > 200:
            raise HTTPException(
                status_code=422, detail="Idempotency-Key must be 1..200 characters"
            )
        existing = session.scalar(select(Job).where(Job.idempotency_key == key))
        if existing is not None:
            if existing.shot_id != shot.id:
                raise HTTPException(
                    status_code=409, detail="idempotency key belongs to another shot"
                )
            return _queued_out(existing, shot)

    active = session.scalar(
        select(Job).where(
            Job.shot_id == shot.id,
            Job.kind == "render_video",
            Job.status.in_(ACTIVE_JOB_STATUSES),
        )
    )
    if active is not None:
        raise HTTPException(
            status_code=409,
            detail={"error": "render_already_active", "job_id": str(active.id)},
        )

    job = Job(
        kind="render_video",
        shot_id=shot.id,
        status="pending",
        idempotency_key=key,
        payload={
            "shot_id": str(shot.id),
            "start_keyframe_artifact_id": str(shot.start_keyframe_artifact_id),
            "queued_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    session.add(job)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        if key is not None:
            existing = session.scalar(select(Job).where(Job.idempotency_key == key))
            if existing is not None and existing.shot_id == shot.id:
                return _queued_out(existing, shot)
        raise HTTPException(
            status_code=409, detail="render is already queued for this shot"
        ) from error
    session.refresh(job)
    return _queued_out(job, shot)
