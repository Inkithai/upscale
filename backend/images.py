"""Image validation, EXIF orientation, transparency flattening, previews."""

from __future__ import annotations

import io
import logging
from typing import Optional, Tuple

from PIL import Image, ImageOps, UnidentifiedImageError

from backend.config import (
    MAX_IMAGE_PIXELS,
    MAX_IMAGE_SIDE,
    MIN_IMAGE_SIDE,
    PREVIEW_MAX_SIDE,
    SUPPORTED_IMAGE_FORMATS,
    TRANSPARENCY_BG,
)
from backend.errors import AppError

log = logging.getLogger("upscale.images")

# Pillow decompression-bomb guard (slightly above our input cap).
Image.MAX_IMAGE_PIXELS = max(MAX_IMAGE_PIXELS * 4, 40_000_000)

_FORMAT_FROM_EXT = {
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".png": "PNG",
    ".webp": "WEBP",
}


def parse_bg(color: str) -> Tuple[int, int, int]:
    raw = (color or "#FFFFFF").strip()
    if raw.startswith("#"):
        raw = raw[1:]
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
    if len(raw) != 6:
        return (255, 255, 255)
    try:
        return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)
    except ValueError:
        return (255, 255, 255)


def sniff_image_format(data: bytes) -> Optional[str]:
    if len(data) < 12:
        return None
    if data[:3] == b"\xff\xd8\xff":
        return "JPEG"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "PNG"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "WEBP"
    return None


def validate_and_open(
    data: bytes,
    filename: str = "image",
) -> tuple[Image.Image, dict]:
    """Validate bytes as a real JPG/PNG/WebP and return a loaded image + meta.

    Does not trust the client filename, extension, or Content-Type.
    """
    if not data:
        raise AppError("invalid_image", "This file is empty.")

    sniffed = sniff_image_format(data)
    if sniffed is None:
        raise AppError(
            "invalid_image",
            "This file is not a valid JPG, PNG, or WebP image.",
        )

    ext = ""
    if "." in filename:
        ext = "." + filename.rsplit(".", 1)[-1].lower()
    declared = _FORMAT_FROM_EXT.get(ext)
    if declared and declared != sniffed:
        raise AppError(
            "disguised_file",
            f"The file claims to be {declared} but the contents are {sniffed}.",
        )

    try:
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as exc:
        log.info("image verify failed: %s", type(exc).__name__)
        raise AppError(
            "corrupt_image",
            "We couldn't read this image. It may be corrupted.",
        ) from None

    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        raise AppError(
            "corrupt_image",
            "We couldn't read this image. It may be corrupted.",
        ) from None

    fmt = (img.format or sniffed or "").upper()
    if fmt == "JPG":
        fmt = "JPEG"
    if fmt not in SUPPORTED_IMAGE_FORMATS:
        img.close()
        raise AppError(
            "unsupported_type",
            "Only JPG, PNG, and WebP images are supported.",
        )

    width, height = img.size
    if width < MIN_IMAGE_SIDE or height < MIN_IMAGE_SIDE:
        img.close()
        raise AppError("invalid_image", "This image has invalid dimensions.")
    if width > MAX_IMAGE_SIDE or height > MAX_IMAGE_SIDE:
        img.close()
        raise AppError(
            "too_many_pixels",
            f"Each side must be at most {MAX_IMAGE_SIDE} pixels.",
        )
    pixels = width * height
    if pixels > MAX_IMAGE_PIXELS:
        img.close()
        raise AppError(
            "too_many_pixels",
            "This image is too large to upscale 4× on this server.",
        )

    meta = {
        "width": width,
        "height": height,
        "format": fmt,
        "mode": img.mode,
        "size": len(data),
        "has_transparency": _has_alpha(img),
    }
    return img, meta


def _has_alpha(img: Image.Image) -> bool:
    if img.mode in ("RGBA", "LA", "PA"):
        return True
    if img.mode == "P" and "transparency" in img.info:
        return True
    return False


def normalize_orientation(img: Image.Image) -> Image.Image:
    """Apply EXIF orientation so phone photos are not unexpectedly rotated."""
    try:
        return ImageOps.exif_transpose(img) or img
    except Exception:
        return img


def flatten_transparency(img: Image.Image, bg: Optional[str] = None) -> Image.Image:
    """Composite onto a solid background. JPEG cannot store alpha.

    Default background is white (configurable via TRANSPARENCY_BG) so
    transparent PNGs/WebPs do not become black.
    """
    color = parse_bg(bg or TRANSPARENCY_BG)
    if img.mode == "P":
        img = img.convert("RGBA")
    if img.mode in ("RGBA", "LA"):
        rgb = Image.new("RGB", img.size, color)
        alpha = img.getchannel("A") if img.mode == "RGBA" else img.getchannel("A")
        rgb.paste(img.convert("RGB"), mask=alpha)
        return rgb
    if img.mode != "RGB":
        return img.convert("RGB")
    return img


def prepare_for_upscale(img: Image.Image) -> Image.Image:
    img = normalize_orientation(img)
    img = flatten_transparency(img)
    return img


def make_preview_jpeg(img: Image.Image, max_side: int = PREVIEW_MAX_SIDE) -> bytes:
    preview = img.convert("RGB")
    preview.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    preview.save(buf, format="JPEG", quality=82, optimize=True)
    return buf.getvalue()
