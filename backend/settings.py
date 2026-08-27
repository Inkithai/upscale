"""User-selectable upscale factor and output-size targets."""

from __future__ import annotations

from typing import Any, Optional

from backend.config import MIN_OUTPUT_SIZE_MB, UPSCALE_FACTOR
from backend.errors import AppError

ALLOWED_SCALES = (2, 4, 8)
OUTPUT_PRESETS_MB = (2, 4, 6, 8, 10, 20)
MIN_ALLOWED_OUTPUT_MB = 0.25
MAX_ALLOWED_OUTPUT_MB = 40.0


def mb_to_bytes(mb: float) -> int:
    return max(1, int(round(float(mb) * 1024 * 1024)))


def _as_float(value: Any, label: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise AppError("invalid_settings", f"{label} must be a number.") from exc


def _base() -> dict:
    scale = int(UPSCALE_FACTOR) if int(UPSCALE_FACTOR) in ALLOWED_SCALES else 4
    return {
        "upscale_factor": scale,
        "min_output_mb": float(MIN_OUTPUT_SIZE_MB),
        "max_output_mb": None,
    }


def default_settings() -> dict:
    return _finalize(_base())


def normalize_settings(raw: Optional[dict], current: Optional[dict] = None) -> dict:
    """Merge request fields onto defaults. 4× and 4 MB remain the product defaults."""
    out = _base()
    if current:
        for key in ("upscale_factor", "min_output_mb", "max_output_mb"):
            if key in current:
                out[key] = current[key]
    if not raw:
        return _finalize(out)

    if "upscale_factor" in raw and raw["upscale_factor"] is not None:
        try:
            scale = int(raw["upscale_factor"])
        except (TypeError, ValueError) as exc:
            raise AppError("invalid_settings", "Upscale factor must be 2×, 4×, or 8×.") from exc
        if scale not in ALLOWED_SCALES:
            raise AppError("invalid_settings", "Upscale factor must be 2×, 4×, or 8×.")
        out["upscale_factor"] = scale

    if "min_output_mb" in raw and raw["min_output_mb"] is not None:
        mb = _as_float(raw["min_output_mb"], "Minimum output size")
        if mb < MIN_ALLOWED_OUTPUT_MB or mb > MAX_ALLOWED_OUTPUT_MB:
            raise AppError(
                "invalid_settings",
                f"Minimum output size must be between {MIN_ALLOWED_OUTPUT_MB:g} and {MAX_ALLOWED_OUTPUT_MB:g} MB.",
            )
        out["min_output_mb"] = mb

    if "max_output_mb" in raw:
        value = raw["max_output_mb"]
        if value in (None, "", False):
            out["max_output_mb"] = None
        else:
            mx = _as_float(value, "Maximum output size")
            if mx < MIN_ALLOWED_OUTPUT_MB or mx > MAX_ALLOWED_OUTPUT_MB:
                raise AppError(
                    "invalid_settings",
                    f"Maximum output size must be between {MIN_ALLOWED_OUTPUT_MB:g} and {MAX_ALLOWED_OUTPUT_MB:g} MB.",
                )
            out["max_output_mb"] = mx

    return _finalize(out)


def _finalize(out: dict) -> dict:
    min_mb = float(out["min_output_mb"])
    max_mb = out.get("max_output_mb")
    if max_mb is not None and float(max_mb) < min_mb:
        raise AppError("invalid_settings", "Maximum output size must be at least the minimum.")
    out["min_output_bytes"] = mb_to_bytes(min_mb)
    out["max_output_bytes"] = mb_to_bytes(max_mb) if max_mb is not None else None
    out["upscale_factor"] = int(out["upscale_factor"])
    out["min_output_mb"] = min_mb
    out["max_output_mb"] = float(max_mb) if max_mb is not None else None
    return out


def extract_settings_payload(body: Any) -> Optional[dict]:
    if not isinstance(body, dict):
        return None
    keys = ("upscale_factor", "min_output_mb", "max_output_mb")
    if not any(k in body for k in keys):
        return None
    return {k: body.get(k) for k in keys}
