from backend.jobs import cleanup_expired, create_job, delete_job
from tests.conftest import rgb_bytes


def test_delete_job_removes_files(client, tmp_path):
    from backend import jobs

    job = create_job([("a.jpg", rgb_bytes("JPEG"))])
    job_dir = jobs.JOBS_DIR / job["id"]
    assert job_dir.exists()
    delete_job(job["id"])
    assert not job_dir.exists()


def test_cleanup_expired(client, monkeypatch):
    from backend import jobs

    job = create_job([("a.jpg", rgb_bytes("JPEG"))])
    job["created_at"] = 0
    monkeypatch.setattr(jobs, "JOB_TTL_SECONDS", 1)
    removed = cleanup_expired(now=10_000)
    assert removed >= 1
    assert job["id"] not in jobs._jobs
