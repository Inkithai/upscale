"""Stable error codes and user-facing messages. Never leak stack traces."""

from __future__ import annotations


class AppError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def error_body(code: str, message: str, **extra) -> dict:
    body = {"error": {"code": code, "message": message}}
    if extra:
        body["error"].update(extra)
    return body


MESSAGES = {
    "unsupported_type": "Upload a JPG, PNG, WebP image or a ZIP of images.",
    "invalid_zip": "That ZIP file could not be read. It may be corrupted.",
    "empty_zip": "No supported images were found in this ZIP.",
    "zip_slip": "This ZIP was rejected because it contains unsafe file paths.",
    "zip_bomb": "This ZIP is too large to extract safely.",
    "too_many_images": "This batch has too many images. Split it into smaller ZIPs.",
    "too_large": "This file exceeds the maximum upload size.",
    "invalid_image": "This file doesn't look like a valid image.",
    "corrupt_image": "We couldn't read this image. It may be corrupted.",
    "too_many_pixels": "This image is too large to upscale 4× on this server.",
    "disguised_file": "The file extension does not match the actual contents.",
    "job_not_found": "This job was not found. It may have expired.",
    "item_not_found": "This image is no longer in the queue.",
    "not_ready": "The file is not ready to download yet.",
    "cancelled": "Processing was cancelled.",
    "upscale_failed": "We couldn't process this image.",
    "output_limit": "We couldn't produce a JPEG of at least 4 MB without exceeding size limits.",
}
