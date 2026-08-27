"""Environment-configurable limits and processing defaults."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    path = ROOT / ".env"
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        os.environ.setdefault(key, value)


_load_dotenv()


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"Invalid integer for {name}: {raw!r}") from exc


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise RuntimeError(f"Invalid number for {name}: {raw!r}") from exc


def _str(name: str, default: str) -> str:
    raw = os.getenv(name)
    return default if raw is None or raw == "" else raw


# Uploads
MAX_UPLOAD_SIZE = _int("MAX_UPLOAD_SIZE", 80 * 1024 * 1024)
MAX_ZIP_SIZE = _int("MAX_ZIP_SIZE", 200 * 1024 * 1024)
MAX_IMAGES_PER_BATCH = _int("MAX_IMAGES_PER_BATCH", 80)
MAX_EXTRACTED_SIZE = _int("MAX_EXTRACTED_SIZE", 400 * 1024 * 1024)
MAX_ZIP_RATIO = _int("MAX_ZIP_RATIO", 200)

# Image limits (input)
MAX_IMAGE_PIXELS = _int("MAX_IMAGE_PIXELS", 12_000_000)
MAX_IMAGE_SIDE = _int("MAX_IMAGE_SIDE", 8000)
MIN_IMAGE_SIDE = _int("MIN_IMAGE_SIDE", 1)

# Output
MIN_OUTPUT_SIZE_MB = _float("MIN_OUTPUT_SIZE_MB", 4.0)
MIN_OUTPUT_BYTES = int(MIN_OUTPUT_SIZE_MB * 1024 * 1024)
UPSCALE_FACTOR = _int("UPSCALE_FACTOR", 4)
JPEG_QUALITY = _int("JPEG_QUALITY", 95)
MAX_OUTPUT_PIXELS = _int("MAX_OUTPUT_PIXELS", 64_000_000)
MAX_OUTPUT_SIDE = _int("MAX_OUTPUT_SIDE", 16000)
JPEG_MAX_ENLARGE_STEPS = _int("JPEG_MAX_ENLARGE_STEPS", 12)

# Runtime
MAX_CONCURRENT_JOBS = max(1, _int("MAX_CONCURRENT_JOBS", 1))
JOB_TTL_SECONDS = _int("JOB_TTL_SECONDS", 60 * 60)
CLEANUP_INTERVAL_SECONDS = _int("CLEANUP_INTERVAL_SECONDS", 5 * 60)
PREVIEW_MAX_SIDE = _int("PREVIEW_MAX_SIDE", 720)
TRANSPARENCY_BG = _str("TRANSPARENCY_BG", "#FFFFFF")
UPSCALE_BACKEND = _str("UPSCALE_BACKEND", "auto").lower()  # auto | espcn | cubic
LOG_LEVEL = _str("LOG_LEVEL", "INFO")

JOBS_DIR = Path(_str("JOBS_DIR", str(ROOT / "jobs")))
MODEL_DIR = Path(_str("MODEL_DIR", str(ROOT / "backend" / "models")))

SUPPORTED_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")
SUPPORTED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}


def public_config() -> dict:
    """Values the UI is allowed to show. No secrets."""
    return {
        "max_upload_size": MAX_UPLOAD_SIZE,
        "max_zip_size": MAX_ZIP_SIZE,
        "max_images_per_batch": MAX_IMAGES_PER_BATCH,
        "max_image_pixels": MAX_IMAGE_PIXELS,
        "min_output_size_mb": MIN_OUTPUT_SIZE_MB,
        "upscale_factor": UPSCALE_FACTOR,
        "jpeg_quality": JPEG_QUALITY,
        "transparency_bg": TRANSPARENCY_BG,
        "supported": ["JPG", "JPEG", "PNG", "WebP", "ZIP"],
    }
