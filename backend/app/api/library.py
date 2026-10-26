"""Библиотека локаций и предметов (WP-04A).

Локации и предметы отличаются только таблицей и полем-владельцем референса,
поэтому оба набора эндпоинтов живут в одном модуле и используют общие helper'ы.
Загрузка изображений не дублируется: она остаётся в
`POST /api/projects/{project_id}/references` с `kind=location_reference|prop_reference`.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_session, require_project
from app.api.schemas import (
    LibraryEntityCreate,
    LibraryEntityDetail,
    LibraryEntitySummary,
    LibraryEntityUpdate,
    ReferenceOut,
)
from app.models import Location, Prop, ReferenceAsset

router = APIRouter(prefix="/api", tags=["library"])

_MAX_SLUG_ATTEMPTS = 100
_MAX_SLUG_LENGTH = 80

_TRANSLIT = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "e",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "i",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "h",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "sch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}


@dataclass(frozen=True)
class _LibraryKind:
    model: type[Location] | type[Prop]
    owner_field: str
    label: str


_LOCATION = _LibraryKind(model=Location, owner_field="location_id", label="location")
_PROP = _LibraryKind(model=Prop, owner_field="prop_id", label="prop")


def _owner_column(kind: _LibraryKind):
    return getattr(ReferenceAsset, kind.owner_field)


def _summary(entity: Location | Prop, reference_count: int) -> LibraryEntitySummary:
    return LibraryEntitySummary(
        id=entity.id,
        project_id=entity.project_id,
        slug=entity.slug,
        name=entity.name,
        description=entity.description,
        status=entity.status,
        reference_count=reference_count,
    )


def _entity_references(
    session: Session, kind: _LibraryKind, entity_id: uuid.UUID
) -> list[ReferenceAsset]:
    return list(
        session.scalars(
            select(ReferenceAsset)
            .where(_owner_column(kind) == entity_id)
            .order_by(ReferenceAsset.created_at, ReferenceAsset.sha256)
        )
    )


def _reference_counts(
    session: Session, project_id: uuid.UUID, kind: _LibraryKind
) -> dict[uuid.UUID, int]:
    column = _owner_column(kind)
    rows = session.execute(
        select(column, func.count())
        .where(ReferenceAsset.project_id == project_id, column.is_not(None))
        .group_by(column)
    )
    return {owner_id: count for owner_id, count in rows}


def _require_entity(
    session: Session, entity_id: uuid.UUID, kind: _LibraryKind
) -> Location | Prop:
    entity = session.get(kind.model, entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail=f"{kind.label} not found")
    return entity


def _list_entities(
    session: Session, project_id: uuid.UUID, kind: _LibraryKind
) -> list[LibraryEntitySummary]:
    require_project(session, project_id)
    model = kind.model
    entities = session.scalars(
        select(model).where(model.project_id == project_id).order_by(model.name)
    )
    counts = _reference_counts(session, project_id, kind)
    return [_summary(entity, counts.get(entity.id, 0)) for entity in entities]


def _entity_detail(
    session: Session, entity_id: uuid.UUID, kind: _LibraryKind
) -> LibraryEntityDetail:
    entity = _require_entity(session, entity_id, kind)
    references = _entity_references(session, kind, entity.id)
    return LibraryEntityDetail(
        **_summary(entity, len(references)).model_dump(),
        references=[ReferenceOut.from_asset(asset) for asset in references],
    )


def _create_entity(
    session: Session,
    project_id: uuid.UUID,
    kind: _LibraryKind,
    payload: LibraryEntityCreate,
) -> LibraryEntitySummary:
    require_project(session, project_id)
    entity = kind.model(
        project_id=project_id,
        slug=_unique_slug(session, kind, project_id, payload.name),
        name=payload.name.strip(),
        description=payload.description,
    )
    session.add(entity)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409, detail={"error": "duplicate_slug"}
        ) from error
    session.refresh(entity)
    return _summary(entity, 0)


def _update_entity(
    session: Session,
    entity_id: uuid.UUID,
    kind: _LibraryKind,
    payload: LibraryEntityUpdate,
) -> LibraryEntitySummary:
    entity = _require_entity(session, entity_id, kind)
    if "name" in payload.model_fields_set:
        if payload.name is None or not payload.name.strip():
            raise HTTPException(status_code=422, detail="name must not be empty")
        entity.name = payload.name.strip()
    if "description" in payload.model_fields_set:
        entity.description = payload.description
    session.commit()
    session.refresh(entity)
    return _summary(entity, len(_entity_references(session, kind, entity.id)))


def _slugify(name: str) -> str:
    transliterated = "".join(
        _TRANSLIT.get(char, char) for char in name.strip().lower()
    )
    slug = re.sub(r"[^a-z0-9]+", "-", transliterated).strip("-")
    return slug[:_MAX_SLUG_LENGTH].strip("-") or "item"


def _unique_slug(
    session: Session, kind: _LibraryKind, project_id: uuid.UUID, name: str
) -> str:
    model = kind.model
    base = _slugify(name)
    slug = base
    for index in range(2, _MAX_SLUG_ATTEMPTS + 2):
        taken = session.scalar(
            select(model.id).where(
                model.project_id == project_id, model.slug == slug
            )
        )
        if taken is None:
            return slug
        slug = f"{base}-{index}"
    raise HTTPException(status_code=409, detail={"error": "duplicate_slug"})


@router.get(
    "/projects/{project_id}/locations", response_model=list[LibraryEntitySummary]
)
def list_locations(
    project_id: uuid.UUID,
    session: Session = Depends(get_session),
) -> list[LibraryEntitySummary]:
    return _list_entities(session, project_id, _LOCATION)


@router.post(
    "/projects/{project_id}/locations",
    response_model=LibraryEntitySummary,
    status_code=status.HTTP_201_CREATED,
)
def create_location(
    project_id: uuid.UUID,
    payload: LibraryEntityCreate,
    session: Session = Depends(get_session),
) -> LibraryEntitySummary:
    return _create_entity(session, project_id, _LOCATION, payload)


@router.get("/locations/{location_id}", response_model=LibraryEntityDetail)
def get_location(
    location_id: uuid.UUID,
    session: Session = Depends(get_session),
) -> LibraryEntityDetail:
    return _entity_detail(session, location_id, _LOCATION)


@router.patch("/locations/{location_id}", response_model=LibraryEntitySummary)
def update_location(
    location_id: uuid.UUID,
    payload: LibraryEntityUpdate,
    session: Session = Depends(get_session),
) -> LibraryEntitySummary:
    return _update_entity(session, location_id, _LOCATION, payload)


@router.get(
    "/projects/{project_id}/props", response_model=list[LibraryEntitySummary]
)
def list_props(
    project_id: uuid.UUID,
    session: Session = Depends(get_session),
) -> list[LibraryEntitySummary]:
    return _list_entities(session, project_id, _PROP)


@router.post(
    "/projects/{project_id}/props",
    response_model=LibraryEntitySummary,
    status_code=status.HTTP_201_CREATED,
)
def create_prop(
    project_id: uuid.UUID,
    payload: LibraryEntityCreate,
    session: Session = Depends(get_session),
) -> LibraryEntitySummary:
    return _create_entity(session, project_id, _PROP, payload)


@router.get("/props/{prop_id}", response_model=LibraryEntityDetail)
def get_prop(
    prop_id: uuid.UUID,
    session: Session = Depends(get_session),
) -> LibraryEntityDetail:
    return _entity_detail(session, prop_id, _PROP)


@router.patch("/props/{prop_id}", response_model=LibraryEntitySummary)
def update_prop(
    prop_id: uuid.UUID,
    payload: LibraryEntityUpdate,
    session: Session = Depends(get_session),
) -> LibraryEntitySummary:
    return _update_entity(session, prop_id, _PROP, payload)
