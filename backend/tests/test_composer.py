"""WP-05: синхронный композитор PNG."""

from __future__ import annotations

import hashlib
import io
import uuid
from pathlib import Path

import pytest
from PIL import Image

from app.composer import (
    CompositionError,
    CompositionLayer,
    CompositionLimitError,
    CompositionSourceError,
    compose,
)
from app.storage import BlobStore


def _png(size: tuple[int, int], color: tuple[int, ...], mode: str = "RGBA") -> bytes:
    image = Image.new(mode, size, color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _store(tmp_path: Path) -> BlobStore:
    return BlobStore(tmp_path / "storage")


def _layer(
    store: BlobStore,
    payload: bytes,
    *,
    kind: str = "character_reference",
    z_index: int = 0,
    x: float = 0,
    y: float = 0,
    scale: float = 1,
    rotation: float = 0,
    opacity: float = 1,
) -> CompositionLayer:
    blob = store.put_bytes(payload, suffix=".png")
    return CompositionLayer(
        reference_asset_id=uuid.uuid4(),
        kind=kind,
        storage_key=blob.storage_key,
        z_index=z_index,
        x=x,
        y=y,
        scale=scale,
        rotation=rotation,
        opacity=opacity,
    )


def _open(png: bytes) -> Image.Image:
    return Image.open(io.BytesIO(png)).convert("RGBA")


def test_two_characters_and_location(tmp_path: Path) -> None:
    store = _store(tmp_path)
    background = _layer(
        store, _png((64, 64), (10, 20, 30, 255)), kind="location_reference", z_index=0
    )
    first = _layer(store, _png((16, 16), (255, 0, 0, 255)), z_index=1, x=4, y=4)
    second = _layer(store, _png((16, 16), (0, 255, 0, 255)), z_index=2, x=12, y=4)

    result = compose(
        [second, background, first],
        width=64,
        height=64,
        store=store,
        max_pixels=1024 * 1024,
        max_layers=8,
    )

    assert (result.width, result.height) == (64, 64)
    image = _open(result.png)
    assert image.mode == "RGBA"
    assert image.getpixel((0, 0)) == (10, 20, 30, 255)
    assert image.getpixel((6, 6)) == (255, 0, 0, 255)
    assert image.getpixel((14, 6)) == (0, 255, 0, 255)
    # Пересечение слоёв: верхний z_index перекрывает нижний.
    overlap = _layer(store, _png((16, 16), (0, 0, 255, 255)), z_index=3, x=6, y=6)
    stacked = compose(
        [background, first, overlap],
        width=64,
        height=64,
        store=store,
        max_pixels=1024 * 1024,
        max_layers=8,
    )
    assert _open(stacked.png).getpixel((8, 8)) == (0, 0, 255, 255)
    assert result.warnings == ()


def test_canvas_keeps_transparency(tmp_path: Path) -> None:
    store = _store(tmp_path)
    layer = _layer(store, _png((10, 10), (255, 0, 0, 255)), z_index=0, x=5, y=7)

    result = compose(
        [layer],
        width=32,
        height=32,
        store=store,
        max_pixels=1024 * 1024,
        max_layers=4,
    )

    image = _open(result.png)
    assert image.getpixel((0, 0))[3] == 0
    assert image.getpixel((6, 8))[3] == 255
    assert image.getpixel((31, 31))[3] == 0


def test_opacity_multiplies_alpha(tmp_path: Path) -> None:
    store = _store(tmp_path)
    layer = _layer(store, _png((8, 8), (255, 0, 0, 255)), z_index=0, opacity=0.5)

    result = compose(
        [layer],
        width=8,
        height=8,
        store=store,
        max_pixels=1024,
        max_layers=2,
    )

    assert _open(result.png).getpixel((4, 4)) == (255, 0, 0, 128)


def test_scale_and_rotation(tmp_path: Path) -> None:
    store = _store(tmp_path)
    scaled = _layer(store, _png((10, 10), (255, 0, 0, 255)), z_index=0, x=20, y=30, scale=2)
    result = compose(
        [scaled],
        width=64,
        height=64,
        store=store,
        max_pixels=4096,
        max_layers=2,
    )
    image = _open(result.png)
    assert image.getpixel((21, 31))[3] == 255
    assert image.getpixel((39, 49))[3] == 255
    assert image.getpixel((19, 29))[3] == 0

    rotated = _layer(store, _png((20, 10), (0, 255, 0, 255)), z_index=0, rotation=90)
    rotated_result = compose(
        [rotated],
        width=32,
        height=32,
        store=store,
        max_pixels=4096,
        max_layers=2,
    )
    rotated_image = _open(rotated_result.png)
    # 20×10 после поворота на 90° по часовой занимает 10×20.
    assert rotated_image.getpixel((5, 10))[3] > 200
    assert rotated_image.getpixel((20, 5))[3] == 0


def test_warnings_for_opaque_layers(tmp_path: Path) -> None:
    store = _store(tmp_path)
    character = _layer(
        store, _png((8, 8), (255, 0, 0), mode="RGB"), z_index=0
    )
    location = _layer(
        store,
        _png((8, 8), (0, 0, 255), mode="RGB"),
        kind="location_reference",
        z_index=1,
    )

    result = compose(
        [character, location],
        width=8,
        height=8,
        store=store,
        max_pixels=1024,
        max_layers=4,
    )

    codes = [warning.code for warning in result.warnings]
    assert codes == ["opaque_character_reference", "layer_without_alpha"]
    assert result.warnings[0].z_index == 0
    assert result.warnings[0].reference_asset_id == character.reference_asset_id


def test_source_blobs_are_not_modified(tmp_path: Path) -> None:
    store = _store(tmp_path)
    payload = _png((8, 8), (255, 0, 0, 255))
    layer = _layer(store, payload, z_index=0)
    path = store.resolve(layer.storage_key)
    before = hashlib.sha256(path.read_bytes()).hexdigest()

    compose(
        [layer],
        width=8,
        height=8,
        store=store,
        max_pixels=1024,
        max_layers=2,
    )

    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert path.read_bytes() == payload


def test_layer_outside_canvas_is_clipped(tmp_path: Path) -> None:
    store = _store(tmp_path)
    layer = _layer(store, _png((8, 8), (255, 0, 0, 255)), z_index=0, x=-100, y=-100)

    result = compose(
        [layer],
        width=16,
        height=16,
        store=store,
        max_pixels=1024,
        max_layers=2,
    )

    image = _open(result.png)
    assert image.getbbox() is None


def test_limits_and_invalid_layers(tmp_path: Path) -> None:
    store = _store(tmp_path)
    layer = _layer(store, _png((4, 4), (255, 0, 0, 255)))

    with pytest.raises(CompositionLimitError):
        compose(
            [layer],
            width=32,
            height=32,
            store=store,
            max_pixels=100,
            max_layers=4,
        )
    with pytest.raises(CompositionLimitError):
        compose(
            [layer, layer],
            width=4,
            height=4,
            store=store,
            max_pixels=1024,
            max_layers=1,
        )
    with pytest.raises(CompositionError):
        compose([], width=4, height=4, store=store, max_pixels=1024, max_layers=2)
    with pytest.raises(CompositionError):
        compose(
            [layer, layer],
            width=4,
            height=4,
            store=store,
            max_pixels=1024,
            max_layers=4,
        )
    with pytest.raises(CompositionSourceError):
        compose(
            [
                CompositionLayer(
                    reference_asset_id=uuid.uuid4(),
                    kind="character_reference",
                    storage_key="blobs/aa/missing.png",
                    z_index=0,
                )
            ],
            width=4,
            height=4,
            store=store,
            max_pixels=1024,
            max_layers=2,
        )
