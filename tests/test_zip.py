from __future__ import annotations

import io
import zipfile

import pytest

from backend.errors import AppError
from backend.ziputil import extract_images_from_zip, is_junk_name
from tests.conftest import make_zip, rgb_bytes


def test_single_image_zip():
    z = make_zip([("photo.jpg", rgb_bytes("JPEG"))])
    out = extract_images_from_zip(z)
    assert len(out) == 1
    assert out[0][0] == "photo.jpg"


def test_multiple_and_nested():
    z = make_zip(
        [
            ("photo1.jpg", rgb_bytes("JPEG")),
            ("photo2.png", rgb_bytes("PNG")),
            ("photo3.webp", rgb_bytes("WEBP")),
            ("folder/photo4.jpg", rgb_bytes("JPEG", color=(10, 10, 10))),
        ]
    )
    out = extract_images_from_zip(z)
    names = [n for n, _ in out]
    assert len(out) == 4
    assert "photo4.jpg" in names


def test_duplicate_filenames():
    z = make_zip(
        [
            ("a/photo.jpg", rgb_bytes("JPEG", color=(1, 2, 3))),
            ("b/photo.jpg", rgb_bytes("JPEG", color=(9, 8, 7))),
        ]
    )
    out = extract_images_from_zip(z)
    names = [n for n, _ in out]
    assert len(set(names)) == 2


def test_unsupported_and_junk_ignored():
    z = make_zip(
        [
            ("readme.txt", b"hello"),
            (".DS_Store", b"junk"),
            ("__MACOSX/._photo.jpg", b"junk"),
            ("Thumbs.db", b"junk"),
            ("keep.png", rgb_bytes("PNG")),
        ]
    )
    out = extract_images_from_zip(z)
    assert len(out) == 1
    assert out[0][0] == "keep.png"


def test_empty_zip():
    z = make_zip([("notes.txt", b"no images")])
    with pytest.raises(AppError) as exc:
        extract_images_from_zip(z)
    assert exc.value.code == "empty_zip"


def test_corrupted_zip():
    with pytest.raises(AppError) as exc:
        extract_images_from_zip(b"not a zip")
    assert exc.value.code in {"invalid_zip", "too_large"}


def test_junk_names():
    assert is_junk_name("__MACOSX/foo")
    assert is_junk_name(".DS_Store")
    assert is_junk_name("folder/Thumbs.db")
    assert not is_junk_name("folder/photo.jpg")
