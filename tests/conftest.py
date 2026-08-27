"""Test env must be set before backend.config is imported."""

from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path

os.environ["MIN_OUTPUT_SIZE_MB"] = "0.0001"
os.environ["UPSCALE_BACKEND"] = "cubic"
os.environ["MAX_IMAGES_PER_BATCH"] = "20"
os.environ["MAX_UPLOAD_SIZE"] = str(4 * 1024 * 1024)
os.environ["MAX_ZIP_SIZE"] = str(4 * 1024 * 1024)
os.environ["MAX_EXTRACTED_SIZE"] = str(6 * 1024 * 1024)
os.environ["MAX_IMAGE_PIXELS"] = "2_000_000"
os.environ["MAX_OUTPUT_PIXELS"] = "8_000_000"
os.environ["JOB_TTL_SECONDS"] = "3600"
os.environ["CLEANUP_INTERVAL_SECONDS"] = "3600"
os.environ["MAX_CONCURRENT_JOBS"] = "1"
os.environ["TRANSPARENCY_BG"] = "#FFFFFF"

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBS_DIR", str(tmp_path / "jobs"))
    from backend import config, jobs

    jobs.JOBS_DIR = tmp_path / "jobs"
    jobs.JOBS_DIR.mkdir()
    config.JOBS_DIR = jobs.JOBS_DIR
    with TestClient(app) as c:
        yield c


def rgb_bytes(fmt: str = "JPEG", size=(32, 24), color=(40, 80, 160), suffix=None) -> bytes:
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    save_fmt = "JPEG" if fmt.upper() in {"JPG", "JPEG"} else fmt.upper()
    kw = {}
    if save_fmt == "JPEG":
        kw["quality"] = 90
    img.save(buf, format=save_fmt, **kw)
    return buf.getvalue()


def png_transparent(size=(16, 16)) -> bytes:
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    img.putpixel((0, 0), (255, 0, 0, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def make_zip(entries: list[tuple[str, bytes]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries:
            zf.writestr(name, data)
    return buf.getvalue()


def wait_job(client: TestClient, job_id: str, timeout: float = 40.0):
    import time

    t0 = time.time()
    last = None
    while time.time() - t0 < timeout:
        res = client.get(f"/api/jobs/{job_id}")
        assert res.status_code == 200
        last = res.json()
        counts = last.get("counts") or {}
        if last["status"] in {"completed", "cancelled", "error"} and counts.get("processing", 0) == 0:
            return last
        if last["status"] in {"ready"} and counts.get("pending", 0) == 0 and counts.get("processing", 0) == 0:
            return last
        time.sleep(0.05)
    raise TimeoutError(last)
