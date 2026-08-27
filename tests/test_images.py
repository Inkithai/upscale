from __future__ import annotations

import io

import pytest
from PIL import Image

from backend.errors import AppError
from backend.images import flatten_transparency, prepare_for_upscale, sniff_image_format, validate_and_open
from tests.conftest import png_transparent, rgb_bytes


@pytest.mark.parametrize("fmt,ext", [("JPEG", "jpg"), ("JPEG", "jpeg"), ("PNG", "png"), ("WEBP", "webp")])
def test_validate_formats(fmt, ext):
    data = rgb_bytes(fmt if fmt != "JPEG" else "JPEG")
    img, meta = validate_and_open(data, f"shot.{ext}")
    expected = "JPEG" if ext in ("jpg", "jpeg") else fmt
    assert meta["format"] == expected
    assert meta["width"] == 32
    assert meta["height"] == 24
    img.close()


def test_sniff_rejects_text_named_jpg():
    data = b"this is not an image at all"
    assert sniff_image_format(data) is None
    with pytest.raises(AppError) as exc:
        validate_and_open(data, "photo.jpg")
    assert exc.value.code == "invalid_image"


def test_extension_mismatch():
    data = rgb_bytes("PNG")
    with pytest.raises(AppError) as exc:
        validate_and_open(data, "photo.jpg")
    assert exc.value.code == "disguised_file"


def test_corrupt_jpeg():
    data = b"\xff\xd8\xff" + b"\x00" * 40
    with pytest.raises(AppError) as exc:
        validate_and_open(data, "broken.jpg")
    assert exc.value.code in {"corrupt_image", "invalid_image"}


def test_transparent_png_flattens_to_white():
    data = png_transparent()
    img, meta = validate_and_open(data, "alpha.png")
    assert meta["has_transparency"] is True
    flat = flatten_transparency(img)
    assert flat.mode == "RGB"
    assert flat.getpixel((1, 1)) == (255, 255, 255)
    assert flat.getpixel((0, 0))[0] == 255
    img.close()


def test_exif_orientation():
    img = Image.new("RGB", (20, 10), (255, 0, 0))
    for x in range(10, 20):
        for y in range(10):
            img.putpixel((x, y), (0, 0, 255))
    exif = img.getexif()
    exif[0x0112] = 6
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95, exif=exif)
    data = buf.getvalue()
    opened, meta = validate_and_open(data, "phone.jpg")
    prepared = prepare_for_upscale(opened)
    # Orientation 6 rotates 90 CW: 20x10 -> 10x20
    assert prepared.size == (10, 20)
    opened.close()


def test_tiny_image_ok():
    data = rgb_bytes("PNG", size=(2, 2))
    img, meta = validate_and_open(data, "tiny.png")
    assert meta["width"] == 2
    img.close()
