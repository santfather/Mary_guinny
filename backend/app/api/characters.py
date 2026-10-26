from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.api.schemas import (
    BibleVersionOut,
    BibleVersionSummary,
    CharacterDetail,
    CharacterSummary,
    ReferenceOut,
)
from app.models import Character, CharacterBibleVersion, Project, ReferenceAsset

router = APIRouter(prefix="/api", tags=["characters"])

CharacterKind = Literal["cat", "human", "other"]
LibraryStatus = Literal["draft", "active", "archived"]
ReferenceStatus = Literal["draft", "approved", "rejected", "superseded"]
ReferenceView = Literal["front", "side", "three_quarter", "back", "other"]
ReferencePose = Literal["stand", "sit", "walk", "lie", "sleep", "custom"]


def _require_project(session: Session, project_id: uuid.UUID) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return project


def _require_character(session: Session, character_id: uuid.UUID) -> Character:
    character = session.get(Character, character_id)
    if character is None:
        raise HTTPException(status_code=404, detail="character not found")
    return character


def _summarize(
    character: Character,
    references: list[ReferenceAsset],
    versions: list[CharacterBibleVersion],
) -> CharacterSummary:
    ordered = sorted(versions, key=lambda item: item.version, reverse=True)
    latest = ordered[0] if ordered else None
    return CharacterSummary(
        id=character.id,
        slug=character.slug,
        name=character.name,
        kind=character.kind,
        status=character.status,
        description=character.description,
        reference_count=len(references),
        approved_reference_count=sum(1 for item in references if item.status == "approved"),
        bible_version_count=len(versions),
        latest_bible_version=latest.version if latest else None,
        latest_bible_status=latest.status if latest else None,
    )


@router.get("/projects/{project_id}/characters", response_model=list[CharacterSummary])
def list_characters(
    project_id: uuid.UUID,
    kind: CharacterKind | None = None,
    status: LibraryStatus | None = None,
    session: Session = Depends(get_session),
) -> list[CharacterSummary]:
    _require_project(session, project_id)

    statement = select(Character).where(Character.project_id == project_id)
    if kind is not None:
        statement = statement.where(Character.kind == kind)
    if status is not None:
        statement = statement.where(Character.status == status)
    characters = list(session.scalars(statement.order_by(Character.name)))

    references: dict[uuid.UUID, list[ReferenceAsset]] = defaultdict(list)
    for asset in session.scalars(
        select(ReferenceAsset).where(
            ReferenceAsset.project_id == project_id,
            ReferenceAsset.character_id.is_not(None),
        )
    ):
        references[asset.character_id].append(asset)  # type: ignore[index]

    versions: dict[uuid.UUID, list[CharacterBibleVersion]] = defaultdict(list)
    for version in session.scalars(
        select(CharacterBibleVersion).where(
            CharacterBibleVersion.project_id == project_id
        )
    ):
        versions[version.character_id].append(version)

    return [
        _summarize(character, references[character.id], versions[character.id])
        for character in characters
    ]


@router.get("/characters/{character_id}", response_model=CharacterDetail)
def get_character(
    character_id: uuid.UUID,
    session: Session = Depends(get_session),
) -> CharacterDetail:
    character = _require_character(session, character_id)

    references = list(
        session.scalars(
            select(ReferenceAsset).where(ReferenceAsset.character_id == character.id)
        )
    )
    versions = list(
        session.scalars(
            select(CharacterBibleVersion).where(
                CharacterBibleVersion.character_id == character.id
            )
        )
    )
    summary = _summarize(character, references, versions)
    ordered = sorted(versions, key=lambda item: item.version, reverse=True)
    return CharacterDetail(
        **summary.model_dump(),
        bible_versions=[BibleVersionSummary.from_version(item) for item in ordered],
    )


@router.get("/characters/{character_id}/bible", response_model=list[BibleVersionOut])
def list_bible_versions(
    character_id: uuid.UUID,
    session: Session = Depends(get_session),
) -> list[BibleVersionOut]:
    _require_character(session, character_id)
    versions = session.scalars(
        select(CharacterBibleVersion)
        .where(CharacterBibleVersion.character_id == character_id)
        .order_by(CharacterBibleVersion.version.desc())
    )
    return [BibleVersionOut.from_version(version) for version in versions]


@router.get("/characters/{character_id}/references", response_model=list[ReferenceOut])
def list_character_references(
    character_id: uuid.UUID,
    status: ReferenceStatus | None = None,
    view: ReferenceView | None = None,
    pose: ReferencePose | None = None,
    session: Session = Depends(get_session),
) -> list[ReferenceOut]:
    _require_character(session, character_id)

    statement = select(ReferenceAsset).where(ReferenceAsset.character_id == character_id)
    if status is not None:
        statement = statement.where(ReferenceAsset.status == status)
    if view is not None:
        statement = statement.where(ReferenceAsset.view == view)
    if pose is not None:
        statement = statement.where(ReferenceAsset.pose == pose)
    statement = statement.order_by(ReferenceAsset.created_at, ReferenceAsset.sha256)

    return [ReferenceOut.from_asset(asset) for asset in session.scalars(statement)]
