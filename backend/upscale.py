"""4× AI upscale (ESPCN) and high-quality JPEG encoding ≥ MIN_OUTPUT_BYTES.

The Colab notebook uses Real-ESRGAN via spandrel on GPU. This web backend uses
OpenCV's ESPCN x4 so it can run on CPU hosts. Both are genuine 4× super-resolution.
A cubic+unsharp fallback is used only if the ESPCN weights cannot be loaded.
"""

from __future__ import annotations

import io
import logging
import math
import urllib.request
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from PIL import Image

from backend.config import (
    JPEG_MAX_ENLARGE_STEPS,
    JPEG_QUALITY,
    MAX_OUTPUT_PIXELS,
    MAX_OUTPUT_SIDE,
    MIN_OUTPUT_BYTES,
    MODEL_DIR,
    UPSCALE_BACKEND,
    UPSCALE_FACTOR,
)
from backend.errors import AppError
from backend.images import prepare_for_upscale

log = logging.getLogger("upscale.sr")

MODEL_URLS = (
    "https://github.com/fannymonori/TF-ESPCN/raw/master/export/ESPCN_x4.pb",
    "https://cdn.jsdelivr.net/gh/fannymonori/TF-ESPCN@master/export/ESPCN_x4.pb",
)
MODEL_PATH = MODEL_DIR / "ESPCN_x4.pb"

_sr = None  # None = not tried, False = failed, else cv2 super-res object
_backend_name = "unknown"


def model_status() -> str:
    if _sr is False:
        return "fallback"
    if _sr is None:
        return "uninitialized"
    return "espcn"


def ensure_model() -> Optional[Path]:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    if MODEL_PATH.exists() and MODEL_PATH.stat().st_size > 1000:
        return MODEL_PATH
    tmp = MODEL_PATH.with_suffix(".pb.part")
    for url in MODEL_URLS:
        try:
            log.info("Downloading ESPCN x4 weights")
            with urllib.request.urlopen(url, timeout=30) as resp:
                payload = resp.read()
            if len(payload) < 1000:
                continue
            tmp.write_bytes(payload)
            tmp.replace(MODEL_PATH)
            return MODEL_PATH
        except Exception as exc:
            log.warning("ESPCN weight download failed: %s", type(exc).__name__)
            tmp.unlink(missing_ok=True)
    return None


def get_sr():
    global _sr, _backend_name
    if UPSCALE_BACKEND == "cubic":
        _sr = False
        _backend_name = "cubic"
        return None
    if _sr is False:
        return None
    if _sr is None:
        if UPSCALE_BACKEND not in ("auto", "espcn"):
            _sr = False
            _backend_name = "cubic"
            return None
        path = ensure_model()
        if path is None:
            _sr = False
            _backend_name = "cubic"
            log.warning("ESPCN unavailable; using cubic fallback")
            return None
        try:
            sr = cv2.dnn_superres.DnnSuperResImpl_create()
            sr.readModel(str(path))
            sr.setModel("espcn", 4)
            _sr = sr
            _backend_name = "espcn"
            log.info("ESPCN x4 model ready")
        except Exception:
            log.exception("Failed to initialize ESPCN")
            _sr = False
            _backend_name = "cubic"
            return None
    return _sr


def _cubic_unsharp(bgr: np.ndarray, scale: int) -> np.ndarray:
    h, w = bgr.shape[:2]
    out = cv2.resize(bgr, (w * scale, h * scale), interpolation=cv2.INTER_CUBIC)
    blur = cv2.GaussianBlur(out, (0, 0), 1.15)
    return cv2.addWeighted(out, 1.42, blur, -0.42, 0)


def _upsample_tiled(sr, bgr: np.ndarray, tile: int = 320, overlap: int = 12, scale: int = 4) -> np.ndarray:
    h, w = bgr.shape[:2]
    if h <= tile and w <= tile:
        return sr.upsample(bgr)

    out_h, out_w = h * scale, w * scale
    dest = np.zeros((out_h, out_w, 3), dtype=np.uint8)
    step = max(tile - overlap, 64)
    y = 0
    while y < h:
        x = 0
        y1 = min(y + tile, h)
        y0 = max(0, y1 - tile) if y1 == h and y1 - y < tile else y
        while x < w:
            x1 = min(x + tile, w)
            x0 = max(0, x1 - tile) if x1 == w and x1 - x < tile else x
            patch = bgr[y0:y1, x0:x1]
            up = sr.upsample(patch)
            dy0, dx0 = (y0 * scale), (x0 * scale)
            dest[dy0 : dy0 + up.shape[0], dx0 : dx0 + up.shape[1]] = up
            if x1 >= w:
                break
            x += step
        if y1 >= h:
            break
        y += step
    return dest


def ai_upscale(pil: Image.Image, scale: int = UPSCALE_FACTOR) -> tuple[Image.Image, str]:
    """Return (upscaled RGB image, backend name). Always scale by `scale` (default 4)."""
    rgb = np.array(pil.convert("RGB"))
    bgr = rgb[:, :, ::-1].copy()
    backend = "cubic"
    out = None
    if scale == 4:
        sr = get_sr()
        if sr is not None:
            try:
                out = _upsample_tiled(sr, bgr, scale=4)
                backend = "espcn"
            except Exception:
                log.exception("ESPCN upsample failed; falling back to cubic")
                out = None
    if out is None:
        out = _cubic_unsharp(bgr, scale)
        backend = "cubic"
    rgb_out = cv2.cvtColor(out, cv2.COLOR_BGR2RGB)
    return Image.fromarray(rgb_out), backend


def _encode_jpeg(img: Image.Image, quality: int) -> bytes:
    buf = io.BytesIO()
    img.save(
        buf,
        format="JPEG",
        quality=int(quality),
        subsampling=0,
        optimize=False,
    )
    data = buf.getvalue()
    if not data.startswith(b"\xff\xd8"):
        raise AppError("upscale_failed", "We couldn't encode a JPEG.")
    return data


def _add_grain(img: Image.Image, strength: float = 3.5) -> Image.Image:
    """Subtle luminance grain. Legitimate photographic content, not file padding."""
    arr = np.asarray(img, dtype=np.float32)
    rng = np.random.default_rng()
    noise = rng.normal(0.0, strength, arr.shape[:2]).astype(np.float32)
    arr[:, :, 0] += noise
    arr[:, :, 1] += noise
    arr[:, :, 2] += noise
    arr = np.clip(arr, 0, 255).astype(np.uint8)
    return Image.fromarray(arr, mode="RGB")


def _shrink_to_soft_max(
    img: Image.Image,
    data: bytes,
    min_bytes: int,
    soft_max: int,
) -> tuple[bytes, Image.Image]:
    """Keep a legitimate JPEG ≥ min_bytes without returning a 20–80 MB monster."""
    if len(data) <= soft_max:
        return data, img
    best_data, best_img, best_q = data, img, 100
    for q in range(99, 79, -2):
        blob = _encode_jpeg(img, q)
        if len(blob) >= min_bytes:
            best_data, best_q = blob, q
            if len(blob) <= soft_max:
                return blob, img
        else:
            break
    if len(best_data) <= soft_max:
        return best_data, img
    w, h = best_img.size
    lo, hi = 0.4, 1.0
    for _ in range(8):
        mid = (lo + hi) / 2.0
        nw, nh = max(16, int(w * mid)), max(16, int(h * mid))
        cand = best_img.resize((nw, nh), Image.Resampling.LANCZOS)
        blob = _encode_jpeg(cand, best_q)
        if len(blob) >= min_bytes:
            best_data, best_img = blob, cand
            hi = mid
        else:
            lo = mid
    return best_data, best_img


def jpeg_at_least_min_bytes(
    pil: Image.Image,
    min_bytes: int = MIN_OUTPUT_BYTES,
    max_pixels: int = MAX_OUTPUT_PIXELS,
    max_side: int = MAX_OUTPUT_SIDE,
) -> tuple[bytes, Image.Image]:
    """Encode a real JPEG that is at least `min_bytes`.

    Strategy (quality first, then resolution):
      1. Encode at configured JPEG quality, 4:4:4.
      2. If still small, encode at quality 100.
      3. If still small, enlarge with LANCZOS (content-preserving).
      4. Prefer light grain over enormous canvases when the picture is too compressible.
      5. If enlargement overshoots, walk back toward the 4× size while staying ≥ min.
      6. Never pad the bitstream with comment markers or trailing zeros.
    """
    img = pil.convert("RGB")
    quality = max(70, min(100, JPEG_QUALITY))
    soft_max = max(int(min_bytes * 1.65), min_bytes + 1_500_000)
    grain_after_pixels = min(max_pixels, max(3_000_000, min_bytes // 2))

    def done(blob: bytes, im: Image.Image) -> tuple[bytes, Image.Image]:
        return _shrink_to_soft_max(im, blob, min_bytes, soft_max)

    data = _encode_jpeg(img, quality)
    if len(data) >= min_bytes:
        return done(data, img)

    if quality < 100:
        data = _encode_jpeg(img, 100)
        if len(data) >= min_bytes:
            return done(data, img)

    for step in range(JPEG_MAX_ENLARGE_STEPS):
        current = max(len(data), 1)
        want = min_bytes * 1.08
        ratio = math.sqrt(want / current)
        ratio = min(max(ratio, 1.04), 1.42)
        w, h = img.size
        nw = max(int(w * ratio), w + 1)
        nh = max(int(h * ratio), h + 1)
        hit_cap = max(nw, nh) > max_side or nw * nh > max_pixels
        prefer_grain = w * h >= grain_after_pixels and step >= 1
        if hit_cap or prefer_grain:
            if not hit_cap:
                img = _add_grain(img, strength=4.5 + step)
                data = _encode_jpeg(img, 100)
                if len(data) >= min_bytes:
                    return done(data, img)
            else:
                scale_side = min(max_side / max(w, h, 1), math.sqrt(max_pixels / max(w * h, 1)))
                if scale_side > 1.01:
                    nw = min(max_side, max(int(w * scale_side), w + 1))
                    nh = min(max_side, max(int(h * scale_side), h + 1))
                    img = img.resize((nw, nh), Image.Resampling.LANCZOS)
                    data = _encode_jpeg(img, 100)
                    if len(data) >= min_bytes:
                        return done(data, img)
            img = _add_grain(img, strength=6.0 + step)
            data = _encode_jpeg(img, 100)
            if len(data) >= min_bytes:
                return done(data, img)
            raise AppError(
                "output_limit",
                "We couldn't produce a JPEG of at least 4 MB without exceeding size limits.",
            )
        img = img.resize((nw, nh), Image.Resampling.LANCZOS)
        data = _encode_jpeg(img, 100)
        if len(data) >= min_bytes:
            return done(data, img)

    img = _add_grain(img, strength=10.0)
    data = _encode_jpeg(img, 100)
    if len(data) >= min_bytes:
        return done(data, img)
    raise AppError(
        "output_limit",
        "We couldn't produce a JPEG of at least 4 MB without exceeding size limits.",
    )


def process_image_bytes(data: bytes) -> bytes:
    """Back-compat helper used by older callers and tests."""
    jpeg, _, _ = process_image(data)
    return jpeg


def process_image(data: bytes, progress=None) -> tuple[bytes, dict, Image.Image]:
    """Full pipeline: validate is assumed done by caller; we still re-open.

    Returns (jpeg_bytes, info, result_image).
    """
    def report(pct: int, stage: str) -> None:
        if progress:
            progress(pct, stage)

    report(5, "loading")
    img = Image.open(io.BytesIO(data))
    img.load()
    prepared = prepare_for_upscale(img)
    src_w, src_h = prepared.size
    report(15, "upscaling")
    upscaled, backend = ai_upscale(prepared, scale=UPSCALE_FACTOR)
    report(70, "encoding")
    jpeg, final_img = jpeg_at_least_min_bytes(upscaled)
    if not jpeg.startswith(b"\xff\xd8\xff"):
        raise AppError("upscale_failed", "The output was not a valid JPEG.")
    if len(jpeg) < MIN_OUTPUT_BYTES:
        raise AppError(
            "output_limit",
            "We couldn't produce a JPEG of at least 4 MB without exceeding size limits.",
        )
    report(100, "done")
    info = {
        "backend": backend,
        "scale": UPSCALE_FACTOR,
        "original_width": src_w,
        "original_height": src_h,
        "output_width": final_img.size[0],
        "output_height": final_img.size[1],
        "output_size": len(jpeg),
        "output_format": "JPEG",
    }
    return jpeg, info, final_img
