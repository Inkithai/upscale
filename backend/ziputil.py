"""Safe ZIP handling: Zip Slip, bombs, junk files, nested folders."""

from __future__ import annotations

import io
import logging
import zipfile
from pathlib import Path
from typing import Iterable, List, Tuple

from backend.config import (
    MAX_EXTRACTED_SIZE,
    MAX_IMAGES_PER_BATCH,
    MAX_ZIP_RATIO,
    MAX_ZIP_SIZE,
    SUPPORTED_IMAGE_EXTS,
)
from backend.errors import AppError

log = logging.getLogger("upscale.zip")

_JUNK_NAMES = {".ds_store", "thumbs.db", "desktop.ini"}


def is_junk_name(name: str) -> bool:
    normalized = name.replace("\\", "/").lower()
    if normalized.startswith("__macosx/") or "/__macosx/" in normalized:
        return True
    base = Path(normalized).name
    if base in _JUNK_NAMES:
        return True
    if base.startswith("._"):
        return True
    return False


def is_supported_image_name(name: str) -> bool:
    return Path(name).suffix.lower() in SUPPORTED_IMAGE_EXTS


def unique_label(filename: str, used: set[str]) -> str:
    base = Path(filename).name or "image"
    if base not in used:
        used.add(base)
        return base
    stem = Path(base).stem
    suffix = Path(base).suffix
    n = 1
    while True:
        candidate = f"{stem}_{n}{suffix}"
        if candidate not in used:
            used.add(candidate)
            return candidate
        n += 1


def _safe_member_path(name: str) -> str:
    """Return a relative posix path or raise if the member is unsafe."""
    raw = name.replace("\\", "/")
    if raw.startswith("/") or raw.startswith("\\"):
        raise AppError("zip_slip", "This ZIP was rejected because it contains unsafe file paths.")
    # Reject drive letters and empty
    if ":" in raw.split("/")[0]:
        raise AppError("zip_slip", "This ZIP was rejected because it contains unsafe file paths.")
    parts = []
    for part in raw.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise AppError("zip_slip", "This ZIP was rejected because it contains unsafe file paths.")
        parts.append(part)
    if not parts:
        raise AppError("zip_slip", "This ZIP was rejected because it contains unsafe file paths.")
    return "/".join(parts)


def inspect_zip(data: bytes) -> None:
    if len(data) > MAX_ZIP_SIZE:
        raise AppError("too_large", "This ZIP exceeds the maximum upload size.")
    if len(data) < 4 or data[:2] != b"PK":
        raise AppError("invalid_zip", "That ZIP file could not be read. It may be corrupted.")


def extract_images_from_zip(data: bytes) -> List[Tuple[str, bytes]]:
    """Extract supported images from a ZIP without writing unsafe paths.

    Returns a list of (display_name, bytes). Nested folders are flattened
    for processing; the original relative path is used to disambiguate names.
    """
    inspect_zip(data)
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise AppError("invalid_zip", "That ZIP file could not be read. It may be corrupted.") from exc

    images: List[Tuple[str, bytes]] = []
    used_names: set[str] = set()
    extracted_total = 0
    image_candidates = 0

    try:
        infos = zf.infolist()
    except Exception as exc:
        zf.close()
        raise AppError("invalid_zip", "That ZIP file could not be read. It may be corrupted.") from exc

    uncompressed_declared = 0
    compressed_total = 0
    for info in infos:
        if info.is_dir() or is_junk_name(info.filename):
            continue
        uncompressed_declared += max(info.file_size, 0)
        compressed_total += max(info.compress_size, 0)
        if is_supported_image_name(info.filename):
            image_candidates += 1

    if uncompressed_declared > MAX_EXTRACTED_SIZE:
        zf.close()
        raise AppError("zip_bomb", "This ZIP is too large to extract safely.")
    if compressed_total and uncompressed_declared / max(compressed_total, 1) > MAX_ZIP_RATIO:
        # Extremely high compression ratio is a classic zip-bomb signal.
        if uncompressed_declared > 8 * 1024 * 1024:
            zf.close()
            raise AppError("zip_bomb", "This ZIP is too large to extract safely.")
    if image_candidates > MAX_IMAGES_PER_BATCH:
        zf.close()
        raise AppError(
            "too_many_images",
            f"A ZIP may contain at most {MAX_IMAGES_PER_BATCH} images.",
        )

    try:
        for info in infos:
            if info.is_dir() or is_junk_name(info.filename):
                continue
            try:
                _safe_member_path(info.filename)
            except AppError:
                zf.close()
                raise

            if not is_supported_image_name(info.filename):
                log.info("zip skipped non-image member")
                continue

            if info.file_size > MAX_EXTRACTED_SIZE:
                zf.close()
                raise AppError("zip_bomb", "This ZIP is too large to extract safely.")

            try:
                payload = zf.read(info)
            except Exception as exc:
                log.info("zip member unreadable: %s", type(exc).__name__)
                continue

            extracted_total += len(payload)
            if extracted_total > MAX_EXTRACTED_SIZE:
                zf.close()
                raise AppError("zip_bomb", "This ZIP is too large to extract safely.")

            rel = info.filename.replace("\\", "/")
            display = unique_label(Path(rel).name, used_names)
            images.append((display, payload))
    finally:
        zf.close()

    if not images:
        raise AppError("empty_zip", "No supported images were found in this ZIP.")

    log.info("ZIP extracted images=%s bytes=%s", len(images), extracted_total)
    return images


def write_zip(entries: Iterable[Tuple[str, bytes]]) -> bytes:
    """Build a ZIP in memory with collision-safe names."""
    buf = io.BytesIO()
    used: set[str] = set()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, payload in entries:
            safe = unique_label(Path(name).name or "image.jpg", used)
            zf.writestr(safe, payload)
    return buf.getvalue()
