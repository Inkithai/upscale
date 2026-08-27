from __future__ import annotations

import io

from PIL import Image

from backend.upscale import jpeg_at_least_min_bytes, process_image
from tests.conftest import png_transparent, rgb_bytes


def test_jpeg_grows_to_min_without_padding():
    img = Image.new("RGB", (40, 30), (12, 64, 200))
    data, out = jpeg_at_least_min_bytes(img, min_bytes=80_000, max_pixels=8_000_000, max_side=4000)
    assert data.startswith(b"\xff\xd8\xff")
    assert data.rstrip(b"\x00").endswith(b"\xff\xd9") or data.endswith(b"\xff\xd9")
    assert len(data) >= 80_000
    # Must be a real image, not comment-padded garbage
    probe = Image.open(io.BytesIO(data))
    probe.verify()
    opened = Image.open(io.BytesIO(data))
    assert opened.format == "JPEG"
    assert opened.size[0] * opened.size[1] > 40 * 30
    opened.close()


def test_process_png_and_webp_to_jpeg():
    for data, name in (
        (rgb_bytes("PNG", size=(24, 24)), "a.png"),
        (rgb_bytes("WEBP", size=(24, 24)), "b.webp"),
        (rgb_bytes("JPEG", size=(24, 24)), "c.jpg"),
        (png_transparent((20, 20)), "d.png"),
    ):
        jpeg, info, img = process_image(data)
        assert jpeg.startswith(b"\xff\xd8")
        assert info["output_format"] == "JPEG"
        assert info["scale"] == 4
        assert info["output_width"] >= 24 * 4 or info["output_width"] >= 20
        img.close()


def test_four_mb_floor_is_real_jpeg_not_huge():
    img = Image.new("RGB", (48, 36), (20, 90, 180))
    data, _out = jpeg_at_least_min_bytes(img, min_bytes=4 * 1024 * 1024)
    assert data.startswith(b"\xff\xd8\xff")
    assert data.endswith(b"\xff\xd9")
    assert len(data) >= 4 * 1024 * 1024
    assert len(data) <= 12 * 1024 * 1024
    probe = Image.open(io.BytesIO(data))
    assert probe.format == "JPEG"
    probe.close()


def test_process_image_bytes_compat():
    from backend.upscale import process_image_bytes

    jpeg = process_image_bytes(rgb_bytes("JPEG", size=(16, 16)))
    assert jpeg[:3] == b"\xff\xd8\xff"
    assert len(jpeg) >= 1
