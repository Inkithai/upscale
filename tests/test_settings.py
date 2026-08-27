from __future__ import annotations

import pytest

from backend.errors import AppError
from backend.settings import normalize_settings
from backend.upscale import process_image
from tests.conftest import rgb_bytes, wait_job


def test_normalize_defaults():
    s = normalize_settings(None)
    assert s["upscale_factor"] == 4
    assert s["min_output_mb"] == 0.0001  # test env
    assert s["max_output_mb"] is None


def test_normalize_rejects_bad_scale():
    with pytest.raises(AppError) as exc:
        normalize_settings({"upscale_factor": 3})
    assert exc.value.code == "invalid_settings"


def test_normalize_rejects_max_below_min():
    with pytest.raises(AppError) as exc:
        normalize_settings({"min_output_mb": 8, "max_output_mb": 2})
    assert exc.value.code == "invalid_settings"


def test_process_image_2x():
    jpeg, info, img = process_image(rgb_bytes("PNG", size=(20, 16)), scale=2, min_bytes=200)
    assert info["scale"] == 2
    assert info["output_width"] >= 40
    assert jpeg.startswith(b"\xff\xd8")
    img.close()


def test_api_scale_2(client):
    res = client.post("/api/jobs", files=[("files", ("a.png", rgb_bytes("PNG", size=(24, 18))))])
    job_id = res.json()["id"]
    start = client.post(f"/api/jobs/{job_id}/process", json={"upscale_factor": 2})
    assert start.status_code == 200
    assert start.json()["settings"]["upscale_factor"] == 2
    done = wait_job(client, job_id)
    assert done["items"][0]["status"] == "completed"
    assert done["items"][0]["output"]["scale"] == 2


def test_api_rejects_invalid_settings(client):
    job = client.post("/api/jobs", files=[("files", ("a.jpg", rgb_bytes("JPEG")))]).json()
    bad = client.post(f"/api/jobs/{job['id']}/process", json={"upscale_factor": 5})
    assert bad.status_code == 400
    bad2 = client.post(
        f"/api/jobs/{job['id']}/process",
        json={"min_output_mb": 10, "max_output_mb": 1},
    )
    assert bad2.status_code == 400
