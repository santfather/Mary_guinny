from __future__ import annotations

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

BLOB_PREFIX = "blobs"
TMP_PREFIX = "tmp"
_SUFFIX_RE = re.compile(r"^\.[A-Za-z0-9]{1,16}$")
_CHUNK_SIZE = 1 << 20


class StorageError(ValueError):
    """Некорректный storage_key или операция записи в storage."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_storage_key(key: str) -> str:
    """Проверяет, что ключ относительный и не выходит за корень storage.

    В БД и API допускаются только относительные POSIX-пути (AGENTS.md §5).
    """

    if not isinstance(key, str) or not key.strip():
        raise StorageError("storage_key must be a non-empty string")
    if "\x00" in key:
        raise StorageError("storage_key must not contain NUL bytes")
    if "\\" in key:
        raise StorageError("storage_key must use forward slashes")
    # Проверяем сырые сегменты: PurePosixPath("a//b") молча схлопывает пустые.
    if any(part in ("", ".", "..") for part in key.split("/")):
        raise StorageError(f"storage_key must not contain '.', '..' or empty segments: {key!r}")
    path = PurePosixPath(key)
    if path.is_absolute():
        raise StorageError(f"storage_key must be relative: {key!r}")
    return key


def validate_suffix(suffix: str) -> str:
    if not suffix:
        return ""
    if not _SUFFIX_RE.match(suffix):
        raise StorageError(f"invalid file suffix: {suffix!r}")
    return suffix.lower()


@dataclass(frozen=True)
class StoredBlob:
    storage_key: str
    sha256: str
    size: int
    created: bool


class BlobStore:
    """Content-addressed локальный storage с атомарной публикацией.

    Файл лежит по ключу `blobs/<aa>/<sha256><ext>`; одинаковые байты занимают
    одно место независимо от числа записей в БД.
    """

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).expanduser().resolve()

    def key_for(self, sha256: str, suffix: str = "") -> str:
        if not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise StorageError(f"invalid sha256: {sha256!r}")
        suffix = validate_suffix(suffix)
        return f"{BLOB_PREFIX}/{sha256[:2]}/{sha256}{suffix}"

    def resolve(self, storage_key: str) -> Path:
        key = validate_storage_key(storage_key)
        path = (self.root / key).resolve()
        if path != self.root and self.root not in path.parents:
            raise StorageError(f"storage_key escapes storage root: {storage_key!r}")
        return path

    def exists(self, storage_key: str) -> bool:
        return self.resolve(storage_key).is_file()

    def read_bytes(self, storage_key: str) -> bytes:
        return self.resolve(storage_key).read_bytes()

    def put_bytes(self, data: bytes, *, suffix: str = "") -> StoredBlob:
        digest = hashlib.sha256(data).hexdigest()
        key = self.key_for(digest, suffix)
        target = self.resolve(key)
        if target.is_file():
            return StoredBlob(key, digest, target.stat().st_size, created=False)
        self._publish(self._write_temp(data), target)
        return StoredBlob(key, digest, len(data), created=True)

    def put_file(self, source: Path, *, suffix: str | None = None) -> StoredBlob:
        source = Path(source)
        resolved_suffix = source.suffix if suffix is None else suffix
        temp_path, digest, size = self._copy_to_temp(source)
        key = self.key_for(digest, resolved_suffix)
        target = self.resolve(key)
        if target.is_file():
            temp_path.unlink(missing_ok=True)
            return StoredBlob(key, digest, target.stat().st_size, created=False)
        self._publish(temp_path, target)
        return StoredBlob(key, digest, size, created=True)

    def _tmp_dir(self) -> Path:
        tmp = self.root / TMP_PREFIX
        tmp.mkdir(parents=True, exist_ok=True)
        return tmp

    def _write_temp(self, data: bytes) -> Path:
        fd, name = tempfile.mkstemp(dir=self._tmp_dir(), prefix="blob-")
        path = Path(name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return path

    def _copy_to_temp(self, source: Path) -> tuple[Path, str, int]:
        fd, name = tempfile.mkstemp(dir=self._tmp_dir(), prefix="blob-")
        path = Path(name)
        digest = hashlib.sha256()
        size = 0
        try:
            with source.open("rb") as reader, os.fdopen(fd, "wb") as writer:
                for chunk in iter(lambda: reader.read(_CHUNK_SIZE), b""):
                    digest.update(chunk)
                    writer.write(chunk)
                    size += len(chunk)
                writer.flush()
                os.fsync(writer.fileno())
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return path, digest.hexdigest(), size

    def _publish(self, temp_path: Path, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.replace(temp_path, target)
        except BaseException:
            temp_path.unlink(missing_ok=True)
            raise
