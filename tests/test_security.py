from __future__ import annotations

import io
import zipfile

import pytest

from backend.errors import AppError
from backend.ziputil import extract_images_from_zip, _safe_member_path
from tests.conftest import rgb_bytes


def _zip_with_name(name: str, payload: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, payload)
    return buf.getvalue()


def test_zip_slip_parent_path():
    with pytest.raises(AppError) as exc:
        _safe_member_path("../evil.jpg")
    assert exc.value.code == "zip_slip"


def test_zip_slip_absolute():
    with pytest.raises(AppError) as exc:
        _safe_member_path("/tmp/evil.jpg")
    assert exc.value.code == "zip_slip"


def test_zip_slip_extracted():
    data = _zip_with_name("../outside.jpg", rgb_bytes("JPEG"))
    with pytest.raises(AppError) as exc:
        extract_images_from_zip(data)
    assert exc.value.code == "zip_slip"


def test_zip_bomb_declared_size(monkeypatch):
    import backend.ziputil as zu

    monkeypatch.setattr(zu, "MAX_EXTRACTED_SIZE", 1024)
    payload = b"\x00" * 50_000
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("big.jpg", payload)
    with pytest.raises(AppError) as exc:
        extract_images_from_zip(buf.getvalue())
    assert exc.value.code in {"zip_bomb", "too_many_images", "invalid_image", "empty_zip"}


def test_oversized_zip_header(monkeypatch):
    import backend.ziputil as zu

    monkeypatch.setattr(zu, "MAX_ZIP_SIZE", 100)
    with pytest.raises(AppError) as exc:
        extract_images_from_zip(b"PK" + b"\x00" * 200)
    assert exc.value.code == "too_large"
