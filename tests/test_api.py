from __future__ import annotations

import io
import zipfile

from tests.conftest import make_zip, png_transparent, rgb_bytes, wait_job


def _upload(client, filename: str, data: bytes):
    res = client.post("/api/jobs", files=[("files", (filename, data))])
    return res


def test_single_jpg_process_and_download(client):
    res = _upload(client, "holiday.jpg", rgb_bytes("JPEG", size=(48, 32)))
    assert res.status_code == 200
    job = res.json()
    assert job["total"] == 1
    assert job["items"][0]["status"] == "pending"
    job_id = job["id"]
    start = client.post(f"/api/jobs/{job_id}/process")
    assert start.status_code == 200
    done = wait_job(client, job_id)
    item = done["items"][0]
    assert item["status"] == "completed"
    assert item["output"]["format"] == "JPEG"
    assert item["output"]["scale"] == 4
    dl = client.get(item["download_url"])
    assert dl.status_code == 200
    assert dl.headers["content-type"].startswith("image/jpeg")
    assert dl.content.startswith(b"\xff\xd8")
    assert dl.content.endswith(b"\xff\xd9")
    prev = client.get(item["preview_url"])
    assert prev.status_code == 200


def test_zip_batch_partial_and_retry(client, monkeypatch):
    good = rgb_bytes("PNG", size=(20, 20))
    also = rgb_bytes("WEBP", size=(18, 18))
    z = make_zip(
        [
            ("ok1.png", good),
            ("nested/ok2.webp", also),
            ("skip.txt", b"nope"),
            ("ok3.jpg", rgb_bytes("JPEG", size=(22, 16))),
        ]
    )
    res = _upload(client, "images.zip", z)
    assert res.status_code == 200
    job = res.json()
    assert job["total"] == 3
    job_id = job["id"]
    client.post(f"/api/jobs/{job_id}/process")
    done = wait_job(client, job_id)
    assert done["counts"]["completed"] == 3
    zres = client.get(f"/api/jobs/{job_id}/zip")
    assert zres.status_code == 200
    assert zres.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(zres.content)) as zf:
        names = zf.namelist()
        assert len(names) == 3
        assert len(set(names)) == 3
        for n in names:
            assert n.endswith(".jpg")


def test_invalid_image_does_not_kill_batch(client):
    files = [
        ("files", ("good.png", rgb_bytes("PNG"), "image/png")),
        ("files", ("bad.jpg", b"not-an-image", "image/jpeg")),
    ]
    res = client.post("/api/jobs", files=files)
    assert res.status_code == 200
    job = res.json()
    assert job["total"] == 2
    statuses = {it["filename"]: it["status"] for it in job["items"]}
    assert statuses["good.png"] == "pending"
    assert statuses["bad.jpg"] == "failed"
    job_id = job["id"]
    client.post(f"/api/jobs/{job_id}/process")
    done = wait_job(client, job_id)
    by_name = {it["filename"]: it for it in done["items"]}
    assert by_name["good.png"]["status"] == "completed"
    assert by_name["bad.jpg"]["status"] == "failed"
    assert by_name["bad.jpg"]["error"]
    assert "Traceback" not in (by_name["bad.jpg"]["error"] or "")


def test_retry_failed_without_reupload(client):
    files = [
        ("files", ("good.png", rgb_bytes("PNG"), "image/png")),
        ("files", ("bad.jpg", b"xxxxx", "image/jpeg")),
    ]
    job = client.post("/api/jobs", files=files).json()
    failed = next(it for it in job["items"] if it["status"] == "failed")
    res = client.post(f"/api/jobs/{job['id']}/items/{failed['id']}/retry")
    assert res.status_code == 200


def test_cancel_preserves_completed(client):
    z = make_zip([(f"p{i}.jpg", rgb_bytes("JPEG", size=(16, 16))) for i in range(3)])
    job = _upload(client, "b.zip", z).json()
    job_id = job["id"]
    client.post(f"/api/jobs/{job_id}/process")
    client.post(f"/api/jobs/{job_id}/cancel")
    done = wait_job(client, job_id)
    assert done["status"] in {"cancelled", "completed"}
    # Completed results remain downloadable if any finished before cancel.
    for it in done["items"]:
        if it["status"] == "completed":
            assert client.get(it["download_url"]).status_code == 200
        if it["status"] == "cancelled":
            assert it["error"]


def test_cancel_then_process_resumes_cancelled(client):
    z = make_zip([(f"p{i}.jpg", rgb_bytes("JPEG", size=(16, 16))) for i in range(4)])
    job = _upload(client, "c.zip", z).json()
    job_id = job["id"]
    client.post(f"/api/jobs/{job_id}/process")
    client.post(f"/api/jobs/{job_id}/cancel")
    mid = wait_job(client, job_id)
    if mid["counts"].get("cancelled"):
        client.post(f"/api/jobs/{job_id}/process")
        done = wait_job(client, job_id)
        assert done["counts"]["cancelled"] == 0
        assert done["counts"]["pending"] == 0
        assert done["counts"]["completed"] + done["counts"]["failed"] == done["total"]


def test_unknown_job_404(client):
    res = client.get("/api/jobs/doesnotexist")
    assert res.status_code == 404
    assert res.json()["error"]["message"]


def test_unsupported_type(client):
    res = _upload(client, "notes.txt", b"hello")
    assert res.status_code == 400


def test_empty_zip(client):
    z = make_zip([("readme.txt", b"x")])
    res = _upload(client, "empty.zip", z)
    assert res.status_code == 400


def test_legacy_upload_starts_processing(client):
    res = client.post("/api/upload", files={"file": ("a.jpg", rgb_bytes("JPEG"), "image/jpeg")})
    assert res.status_code == 200
    body = res.json()
    assert body["job_id"]
    done = wait_job(client, body["job_id"])
    assert done["counts"]["completed"] >= 1


def test_remove_and_clear(client):
    job = _upload(client, "a.png", rgb_bytes("PNG")).json()
    item_id = job["items"][0]["id"]
    res = client.delete(f"/api/jobs/{job['id']}/items/{item_id}")
    assert res.status_code == 200
    assert res.json()["total"] == 0
    gone = client.delete(f"/api/jobs/{job['id']}")
    assert gone.status_code == 200
    assert client.get(f"/api/jobs/{job['id']}").status_code == 404


def test_transparent_png_api(client):
    job = _upload(client, "glass.png", png_transparent()).json()
    client.post(f"/api/jobs/{job['id']}/process")
    done = wait_job(client, job["id"])
    assert done["items"][0]["status"] == "completed"
    jpeg = client.get(done["items"][0]["download_url"]).content
    from PIL import Image

    img = Image.open(io.BytesIO(jpeg))
    assert img.format == "JPEG"
    img.close()
