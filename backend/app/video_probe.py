"""Минимальная проверка MP4 без внешних зависимостей (WP-06).

Разбирает только ISO BMFF-боксы, нужные для приёмки результата воркера:
наличие `ftyp`, `moov`, длительность из `mvhd` и видеодорожки (`hdlr` = `vide`).
Полноценный `ffprobe` не подменяется: это проверка контейнера и структуры.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

_FOURCC = 4
_HEADER = 8


class VideoProbeError(ValueError):
    """Файл не является корректным MP4 или не содержит видеодорожку."""


@dataclass(frozen=True)
class Mp4Info:
    duration_s: float
    has_video: bool
    has_audio: bool


def _iter_boxes(data: bytes, start: int, end: int):
    """Итерирует боксы верхнего уровня: (тип, начало данных, конец данных)."""

    offset = start
    while offset + _HEADER <= end:
        size, box_type = struct.unpack(">I4s", data[offset : offset + _HEADER])
        header = _HEADER
        if size == 1:
            if offset + 16 > end:
                raise VideoProbeError("truncated 64-bit box header")
            (size,) = struct.unpack(">Q", data[offset + 8 : offset + 16])
            header = 16
        elif size == 0:
            size = end - offset
        if size < header:
            raise VideoProbeError(f"invalid box size for {box_type!r}")
        box_end = offset + size
        if box_end > end:
            raise VideoProbeError(f"box {box_type!r} exceeds container")
        yield box_type, offset + header, box_end
        offset = box_end


def _find(data: bytes, start: int, end: int, target: bytes) -> tuple[int, int] | None:
    for box_type, body_start, body_end in _iter_boxes(data, start, end):
        if box_type == target:
            return body_start, body_end
    return None


def _children(data: bytes, box: tuple[int, int]):
    return _iter_boxes(data, box[0], box[1])


def _duration(data: bytes, body: tuple[int, int]) -> float:
    start, end = body
    if end - start < 4:
        raise VideoProbeError("mvhd is too short")
    version = data[start]
    if version == 0:
        if end - start < 20:
            raise VideoProbeError("mvhd v0 is too short")
        timescale, duration = struct.unpack(">II", data[start + 12 : start + 20])
    elif version == 1:
        if end - start < 32:
            raise VideoProbeError("mvhd v1 is too short")
        timescale, duration = struct.unpack(">IQ", data[start + 20 : start + 32])
    else:
        raise VideoProbeError(f"unsupported mvhd version {version}")
    if timescale == 0:
        raise VideoProbeError("mvhd timescale is zero")
    return duration / timescale


def _handler_type(data: bytes, body: tuple[int, int]) -> str:
    start, end = body
    if end - start < 12:
        raise VideoProbeError("hdlr is too short")
    return data[start + 8 : start + 12].decode("ascii", errors="replace")


def probe_mp4(data: bytes) -> Mp4Info:
    """Возвращает длительность и наличие дорожек; бросает VideoProbeError."""

    if not data:
        raise VideoProbeError("empty file")
    ftyp = _find(data, 0, len(data), b"ftyp")
    if ftyp is None:
        raise VideoProbeError("missing ftyp box")
    moov = _find(data, 0, len(data), b"moov")
    if moov is None:
        raise VideoProbeError("missing moov box")

    duration: float | None = None
    has_video = False
    has_audio = False
    for box_type, body_start, body_end in _children(data, moov):
        if box_type == b"mvhd":
            duration = _duration(data, (body_start, body_end))
        elif box_type == b"trak":
            hdlr = _find(data, body_start, body_end, b"mdia")
            if hdlr is None:
                continue
            handler = _find(data, hdlr[0], hdlr[1], b"hdlr")
            if handler is None:
                continue
            value = _handler_type(data, handler)
            if value == "vide":
                has_video = True
            elif value == "soun":
                has_audio = True

    if duration is None:
        raise VideoProbeError("missing mvhd box")
    if not has_video:
        raise VideoProbeError("no video track")
    if duration <= 0:
        raise VideoProbeError("video duration is zero")
    return Mp4Info(duration_s=duration, has_video=has_video, has_audio=has_audio)
