from __future__ import annotations

import hashlib

import pytest

from app.storage import BlobStore, StorageError, sha256_file, validate_storage_key


def test_validate_storage_key_accepts_relative_path() -> None:
    assert validate_storage_key("blobs/ab/deadbeef.png") == "blobs/ab/deadbeef.png"


@pytest.mark.parametrize(
    "key",
    [
        "/etc/passwd",
        "../escape.png",
        "blobs/../../escape.png",
        "blobs//empty.png",
        "blobs/./current.png",
        "blobs\\windows.png",
        "with\x00nul.png",
        "",
        "   ",
    ],
)
def test_validate_storage_key_rejects_invalid_paths(key: str) -> None:
    with pytest.raises(StorageError):
        validate_storage_key(key)


def test_resolve_rejects_escape_from_root(tmp_path) -> None:
    store = BlobStore(tmp_path / "storage")
    with pytest.raises(StorageError):
        store.resolve("../outside.png")


def test_put_bytes_is_content_addressed_and_deduplicated(tmp_path) -> None:
    store = BlobStore(tmp_path / "storage")
    payload = b"hello"
    digest = hashlib.sha256(payload).hexdigest()

    first = store.put_bytes(payload, suffix=".txt")
    second = store.put_bytes(payload, suffix=".txt")

    assert first.created is True
    assert first.storage_key == f"blobs/{digest[:2]}/{digest}.txt"
    assert first.sha256 == digest
    assert first.size == len(payload)
    assert second.created is False
    assert second.storage_key == first.storage_key
    assert store.read_bytes(first.storage_key) == payload


def test_put_file_matches_bytes_and_reuses_existing_blob(tmp_path) -> None:
    store = BlobStore(tmp_path / "storage")
    source = tmp_path / "image.png"
    source.write_bytes(b"png-bytes")

    stored = store.put_file(source)
    assert stored.storage_key.endswith(".png")
    assert stored.size == len(b"png-bytes")
    assert sha256_file(source) == stored.sha256

    repeated = store.put_bytes(source.read_bytes(), suffix=".png")
    assert repeated.created is False
    assert repeated.storage_key == stored.storage_key


def test_storage_keeps_temp_directory_clean(tmp_path) -> None:
    store = BlobStore(tmp_path / "storage")
    store.put_bytes(b"payload", suffix=".bin")
    temp_dir = store.root / "tmp"
    assert temp_dir.is_dir()
    assert list(temp_dir.iterdir()) == []


def test_invalid_suffix_and_sha256_are_rejected(tmp_path) -> None:
    store = BlobStore(tmp_path / "storage")
    with pytest.raises(StorageError):
        store.put_bytes(b"payload", suffix="exe")
    with pytest.raises(StorageError):
        store.key_for("not-a-sha")
