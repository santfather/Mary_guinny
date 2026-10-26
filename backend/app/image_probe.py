from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_SIGNATURE = b"\xff\xd8"

# SOF-маркеры JPEG содержат размеры кадра. C4/C8/CC — не SOF.
_JPEG_SOF_MARKERS = frozenset(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}

_MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".mp4": "video/mp4",
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".json": "application/json",
    ".txt": "text/plain",
    ".md": "text/markdown",
}

# ВАЖНО: добавление зависимостей в WP-03 не требовалось (AGENTS.md §6),
# поэтому заголовки PNG/JPEG разбираются вручную.


class ImageProbeError(ValueError):
    """Файл не является поддерживаемым изображением или повреждён."""


@dataclass(frozen=True)
class ImageInfo:
    width: int
    height: int
    mime_type: str
    has_alpha: bool


def guess_mime_type(path: Path) -> str:
    return _MIME_BY_SUFFIX.get(Path(path).suffix.lower(), "application/octet-stream")


def probe_image(path: Path) -> ImageInfo:
    return probe_image_bytes(Path(path).read_bytes())


def probe_image_bytes(data: bytes) -> ImageInfo:
    if data.startswith(PNG_SIGNATURE):
        return _probe_png(data)
    if data.startswith(JPEG_SIGNATURE):
        return _probe_jpeg(data)
    raise ImageProbeError("unsupported image format (expected PNG or JPEG)")


def _probe_png(data: bytes) -> ImageInfo:
    if len(data) < 33:
        raise ImageProbeError("truncated PNG header")
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    if width <= 0 or height <= 0:
        raise ImageProbeError("PNG has invalid dimensions")
    color_type = data[25]
    has_alpha = color_type in (4, 6) or _png_has_trns(data)
    return ImageInfo(width, height, "image/png", has_alpha)


def _png_has_trns(data: bytes) -> bool:
    """tRNS задаёт прозрачность для palette/grayscale/truecolor PNG."""

    offset = len(PNG_SIGNATURE)
    while offset + 8 <= len(data):
        length = int.from_bytes(data[offset : offset + 4], "big")
        chunk_type = data[offset + 4 : offset + 8]
        if chunk_type == b"tRNS":
            return True
        if chunk_type in (b"IDAT", b"IEND"):
            return False
        offset += 12 + length
    return False


def _probe_jpeg(data: bytes) -> ImageInfo:
    offset = len(JPEG_SIGNATURE)
    size = len(data)
    while offset + 4 <= size:
        if data[offset] != 0xFF:
            offset += 1
            continue
        marker = data[offset + 1]
        if marker == 0xFF:
            offset += 1
            continue
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7 or marker == 0x01:
            offset += 2
            continue
        segment_length = int.from_bytes(data[offset + 2 : offset + 4], "big")
        if segment_length < 2:
            raise ImageProbeError("JPEG has invalid segment length")
        if marker in _JPEG_SOF_MARKERS:
            if offset + 9 > size:
                raise ImageProbeError("truncated JPEG SOF segment")
            height = int.from_bytes(data[offset + 5 : offset + 7], "big")
            width = int.from_bytes(data[offset + 7 : offset + 9], "big")
            if width <= 0 or height <= 0:
                raise ImageProbeError("JPEG has invalid dimensions")
            return ImageInfo(width, height, "image/jpeg", False)
        offset += 2 + segment_length
    raise ImageProbeError("JPEG SOF segment not found")
