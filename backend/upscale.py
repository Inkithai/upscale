"""AI upscale via OpenCV DNN Super-Resolution (ESPCN x4) and JPEG sizing."""

from __future__ import annotations

import io
import os
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

TARGET_MIN_BYTES = int(4.1 * 1024 * 1024)
MODEL_DIR = Path(__file__).resolve().parent / "models"
MODEL_URL = (
    "https://github.com/fannymonori/TF-ESPCN/raw/master/export/ESPCN_x4.pb"
)
MODEL_PATH = MODEL_DIR / "ESPCN_x4.pb"

_sr = None


def ensure_model() -> Path | None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    if MODEL_PATH.exists() and MODEL_PATH.stat().st_size > 1000:
        return MODEL_PATH
    import urllib.request

    try:
        tmp = MODEL_PATH.with_suffix(".pb.part")
        urllib.request.urlretrieve(MODEL_URL, tmp)
        tmp.replace(MODEL_PATH)
        return MODEL_PATH
    except Exception:
        return None


def get_sr():
    global _sr
    if _sr is False:
        return None
    if _sr is None:
        path = ensure_model()
        if path is None:
            _sr = False
            return None
        sr = cv2.dnn_superres.DnnSuperResImpl_create()
        sr.readModel(str(path))
        sr.setModel("espcn", 4)
        _sr = sr
    return _sr


def load_image(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    if img.mode in ("RGBA", "LA", "P"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            img = img.convert("RGBA")
        bg.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
        return bg
    return img.convert("RGB")


def ai_upscale(pil: Image.Image) -> Image.Image:
    arr = np.array(pil)[:, :, ::-1]  # RGB -> BGR
    sr = get_sr()
    if sr is not None:
        out = sr.upsample(arr)
    else:
        h, w = arr.shape[:2]
        out = cv2.resize(arr, (w * 4, h * 4), interpolation=cv2.INTER_CUBIC)
        blur = cv2.GaussianBlur(out, (0, 0), 1.2)
        out = cv2.addWeighted(out, 1.45, blur, -0.45, 0)
    rgb = cv2.cvtColor(out, cv2.COLOR_BGR2RGB)
    return Image.fromarray(rgb)


def jpeg_at_least_4mb(pil: Image.Image) -> bytes:
    """Save as JPEG with quality 100; enlarge until file is >= 4.1 MB."""
    img = pil.convert("RGB")
    for _ in range(24):
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=100, optimize=False, subsampling=0)
        data = buf.getvalue()
        if len(data) >= TARGET_MIN_BYTES:
            return data
        # scale so expected size grows roughly with pixel count
        ratio = (TARGET_MIN_BYTES / max(len(data), 1)) ** 0.5
        ratio = min(max(ratio, 1.08), 2.2)
        w, h = img.size
        nw, nh = max(int(w * ratio), w + 1), max(int(h * ratio), h + 1)
        # cap enormous dimensions
        if nw * nh > 80_000_000:
            # pad JPEG with comment / extra chroma by tiling if needed
            return _pad_jpeg(data, TARGET_MIN_BYTES)
        img = img.resize((nw, nh), Image.Resampling.LANCZOS)
    return _pad_jpeg(data, TARGET_MIN_BYTES)


def _pad_jpeg(data: bytes, min_size: int) -> bytes:
    """Append a JPEG COM marker with padding so size meets the floor."""
    if len(data) >= min_size:
        return data
    need = min_size - len(data)
    # JPEG comment marker: FF FE then 2-byte length including the length field
    chunks = []
    remaining = need
    while remaining > 0:
        payload = min(remaining, 65533)
        length = payload + 2
        chunks.append(b"\xff\xfe" + length.to_bytes(2, "big") + b"\x00" * payload)
        remaining -= payload + 4  # marker+length overhead counted in file size
        if remaining <= 0:
            break
        remaining = min_size - (len(data) + sum(len(c) for c in chunks))
    out = data + b"".join(chunks)
    if len(out) < min_size:
        out += b"\x00" * (min_size - len(out))
    return out


def process_image_bytes(data: bytes) -> bytes:
    pil = load_image(data)
    up = ai_upscale(pil)
    return jpeg_at_least_4mb(up)
