"""In-memory job queue with on-disk originals/results and TTL cleanup."""

from __future__ import annotations

import json
import logging
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from backend.config import (
    JOBS_DIR,
    JOB_TTL_SECONDS,
    MAX_CONCURRENT_JOBS,
    MAX_IMAGES_PER_BATCH,
    MAX_UPLOAD_SIZE,
    MAX_ZIP_SIZE,
    SUPPORTED_IMAGE_EXTS,
)
from backend.errors import AppError
from backend.images import make_preview_jpeg, prepare_for_upscale, validate_and_open
from backend.settings import default_settings, normalize_settings
from backend.upscale import process_image
from backend.ziputil import extract_images_from_zip, unique_label, write_zip

log = logging.getLogger("upscale.jobs")

_lock = threading.RLock()
_jobs: dict[str, dict] = {}
_executor = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_JOBS, thread_name_prefix="upscale")
_job_sema = threading.Semaphore(MAX_CONCURRENT_JOBS)


def _now() -> float:
    return time.time()


def _new_id(n: int = 12) -> str:
    return uuid.uuid4().hex[:n]


def _item_dir(job_id: str, item_id: str) -> Path:
    path = JOBS_DIR / job_id / "items" / item_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_stem(name: str) -> str:
    stem = Path(name).stem or "image"
    cleaned = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in stem)
    return cleaned[:80] or "image"


def public_item(job_id: str, item: dict) -> dict:
    item_id = item["id"]
    out = {
        "id": item_id,
        "filename": item["filename"],
        "status": item["status"],
        "progress": item.get("progress", 0),
        "stage": item.get("stage") or "",
        "error": item.get("error"),
        "original": item.get("original"),
        "output": item.get("output"),
        "preview_url": f"/api/jobs/{job_id}/items/{item_id}/preview?which=original",
    }
    if item["status"] == "completed":
        out["result_preview_url"] = f"/api/jobs/{job_id}/items/{item_id}/preview?which=result"
        out["download_url"] = f"/api/jobs/{job_id}/items/{item_id}/file"
        out["download_name"] = item.get("output_name")
    return out


def public_job(job: dict) -> dict:
    items = [public_item(job["id"], it) for it in job["items"]]
    counts = {"pending": 0, "processing": 0, "completed": 0, "failed": 0, "cancelled": 0}
    for it in job["items"]:
        counts[it["status"]] = counts.get(it["status"], 0) + 1
    total = len(job["items"])
    completed = counts["completed"]
    pct = int(round((completed / total) * 100)) if total else 0
    processing_now = next((it["filename"] for it in job["items"] if it["status"] == "processing"), "")
    eta = None
    avg = job.get("avg_seconds")
    waiting = counts["pending"] + counts["processing"]
    if avg and waiting:
        eta = int(avg * waiting)
    return {
        "id": job["id"],
        "status": job["status"],
        "total": total,
        "counts": counts,
        "percent": pct,
        "current": processing_now,
        "eta_seconds": eta,
        "elapsed_seconds": int(max(0, (job.get("finished_at") or _now()) - job["created_at"])),
        "items": items,
        "zip_url": f"/api/jobs/{job['id']}/zip" if counts["completed"] else None,
        "error": job.get("error"),
        "settings": job.get("settings") or default_settings(),
        "upscale_factor": (job.get("settings") or default_settings())["upscale_factor"],
        "min_output_bytes": (job.get("settings") or default_settings()).get(
            "min_output_bytes", 0
        ),
    }


def get_job(job_id: str) -> dict:
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            raise AppError("job_not_found", "This job was not found. It may have expired.", 404)
        return job


def get_item(job: dict, item_id: str) -> dict:
    for it in job["items"]:
        if it["id"] == item_id:
            return it
    raise AppError("item_not_found", "This image is no longer in the queue.", 404)


def _add_image_item(job: dict, filename: str, data: bytes) -> dict:
    item_id = _new_id(10)
    img, meta = validate_and_open(data, filename)
    try:
        oriented = prepare_for_upscale(img)
        preview = make_preview_jpeg(oriented)
        ow, oh = oriented.size
        meta["width"], meta["height"] = ow, oh
    finally:
        img.close()

    d = _item_dir(job["id"], item_id)
    (d / "original.bin").write_bytes(data)
    (d / "preview.jpg").write_bytes(preview)
    (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

    item = {
        "id": item_id,
        "filename": filename,
        "status": "pending",
        "progress": 0,
        "stage": "queued",
        "error": None,
        "original": {
            "width": meta["width"],
            "height": meta["height"],
            "format": meta["format"],
            "size": meta["size"],
            "has_transparency": meta.get("has_transparency", False),
        },
        "output": None,
        "output_name": None,
        "started_at": None,
        "finished_at": None,
    }
    job["items"].append(item)
    return item


def create_job(files: list[tuple[str, bytes]]) -> dict:
    """Create a job from uploaded (filename, bytes) pairs. ZIP members become items."""
    if not files:
        raise AppError("invalid_image", "Upload at least one image or ZIP.")

    job_id = _new_id()
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    work = JOBS_DIR / job_id
    work.mkdir(parents=True, exist_ok=True)

    job = {
        "id": job_id,
        "status": "ready",
        "items": [],
        "created_at": _now(),
        "finished_at": None,
        "cancel": False,
        "error": None,
        "avg_seconds": None,
        "used_names": set(),
        "times": [],
        "running": False,
        "settings": default_settings(),
    }

    pending_images: list[tuple[str, bytes]] = []
    used_labels: set[str] = set()

    for filename, data in files:
        name = Path(filename).name or "upload.bin"
        suffix = Path(name).suffix.lower()
        if suffix == ".zip":
            log.info("Upload validated ZIP job=%s", job_id)
            extracted = extract_images_from_zip(data)
            for label, payload in extracted:
                pending_images.append((unique_label(label, used_labels), payload))
        elif suffix in SUPPORTED_IMAGE_EXTS:
            pending_images.append((unique_label(name, used_labels), data))
        else:
            shutil.rmtree(work, ignore_errors=True)
            raise AppError("unsupported_type", "Upload a JPG, PNG, WebP image or a ZIP of images.")

    if not pending_images:
        shutil.rmtree(work, ignore_errors=True)
        raise AppError("empty_zip", "No supported images were found.")

    if len(pending_images) > MAX_IMAGES_PER_BATCH:
        shutil.rmtree(work, ignore_errors=True)
        raise AppError(
            "too_many_images",
            f"A batch may contain at most {MAX_IMAGES_PER_BATCH} images.",
        )

    with _lock:
        _jobs[job_id] = job
        failures = 0
        for filename, data in pending_images:
            try:
                _add_image_item(job, filename, data)
                log.info("Upload validated image job=%s", job_id)
            except AppError as exc:
                failures += 1
                item_id = _new_id(10)
                job["items"].append(
                    {
                        "id": item_id,
                        "filename": filename,
                        "status": "failed",
                        "progress": 0,
                        "stage": "failed",
                        "error": exc.message,
                        "original": {"width": 0, "height": 0, "format": "unknown", "size": len(data)},
                        "output": None,
                        "output_name": None,
                    }
                )
        if not job["items"]:
            _jobs.pop(job_id, None)
            shutil.rmtree(work, ignore_errors=True)
            raise AppError("invalid_image", "None of the files could be read as images.")

    log.info("Job created id=%s items=%s", job_id, len(job["items"]))
    return job


def start_processing(
    job_id: str,
    only_ids: Optional[list[str]] = None,
    settings: Optional[dict] = None,
) -> dict:
    job = get_job(job_id)
    with _lock:
        if settings:
            job["settings"] = normalize_settings(settings, current=job.get("settings"))
        if job["cancel"] and job["status"] == "cancelled":
            job["cancel"] = False
        if only_ids:
            wanted = set(only_ids)
            for it in job["items"]:
                if it["id"] in wanted and it["status"] in ("failed", "cancelled", "pending"):
                    it["status"] = "pending"
                    it["error"] = None
                    it["progress"] = 0
                    it["stage"] = "queued"
        else:
            for it in job["items"]:
                if it["status"] in ("failed", "cancelled"):
                    continue
        pending = [it for it in job["items"] if it["status"] == "pending"]
        if not pending:
            return job
        job["status"] = "processing"
        job["cancel"] = False
        if not job.get("running"):
            job["running"] = True
            _executor.submit(_run_job, job_id)
    return job


def cancel_job(job_id: str) -> dict:
    job = get_job(job_id)
    with _lock:
        job["cancel"] = True
        for it in job["items"]:
            if it["status"] == "pending":
                it["status"] = "cancelled"
                it["stage"] = "cancelled"
                it["error"] = "Processing was cancelled."
        if job["status"] == "processing":
            job["status"] = "cancelling"
        else:
            job["status"] = "cancelled"
    log.info("Job cancel requested id=%s", job_id)
    return job


def retry_items(
    job_id: str,
    item_ids: Optional[list[str]] = None,
    settings: Optional[dict] = None,
) -> dict:
    job = get_job(job_id)
    with _lock:
        if settings:
            job["settings"] = normalize_settings(settings, current=job.get("settings"))
        job["cancel"] = False
        for it in job["items"]:
            if item_ids is not None and it["id"] not in item_ids:
                continue
            if it["status"] in ("failed", "cancelled"):
                orig = JOBS_DIR / job_id / "items" / it["id"] / "original.bin"
                if not orig.exists():
                    it["error"] = "The original file is no longer available to retry."
                    continue
                it["status"] = "pending"
                it["error"] = None
                it["progress"] = 0
                it["stage"] = "queued"
                it["output"] = None
    return start_processing(job_id, only_ids=None)


def remove_item(job_id: str, item_id: str) -> dict:
    job = get_job(job_id)
    with _lock:
        item = get_item(job, item_id)
        if item["status"] == "processing":
            raise AppError("not_ready", "Stop processing before removing this image.")
        job["items"] = [it for it in job["items"] if it["id"] != item_id]
        shutil.rmtree(JOBS_DIR / job_id / "items" / item_id, ignore_errors=True)
        if not job["items"]:
            job["status"] = "ready"
    return job


def delete_job(job_id: str) -> None:
    with _lock:
        job = _jobs.pop(job_id, None)
        if job:
            job["cancel"] = True
    shutil.rmtree(JOBS_DIR / job_id, ignore_errors=True)
    log.info("Cleanup completed job=%s", job_id)


def _run_job(job_id: str) -> None:
    _job_sema.acquire()
    job = None
    try:
        job = get_job(job_id)
        log.info("Image processing started job=%s", job_id)
        while True:
            with _lock:
                if job.get("cancel"):
                    _finalize_job_locked(job)
                    log.info("Image processing completed job=%s", job_id)
                    return
                nxt = next((it for it in job["items"] if it["status"] == "pending"), None)
                if not nxt:
                    _finalize_job_locked(job)
                    log.info("Image processing completed job=%s", job_id)
                    return
                nxt["status"] = "processing"
                nxt["progress"] = 1
                nxt["stage"] = "starting"
                nxt["started_at"] = _now()
            _process_item(job, nxt)
    except AppError:
        log.info("Image processing failed job=%s", job_id)
        with _lock:
            if job_id in _jobs:
                _jobs[job_id]["running"] = False
                _jobs[job_id]["status"] = "error"
    except Exception:
        log.exception("Image processing failed job=%s", job_id)
        with _lock:
            if job_id in _jobs:
                _jobs[job_id]["running"] = False
                _jobs[job_id]["status"] = "error"
                _jobs[job_id]["error"] = "Processing stopped unexpectedly."
    finally:
        _job_sema.release()


def _finalize_job_locked(job: dict) -> None:
    """Must be called with `_lock` held."""
    job["running"] = False
    counts: dict[str, int] = {}
    for it in job["items"]:
        counts[it["status"]] = counts.get(it["status"], 0) + 1
    if job.get("cancel"):
        job["status"] = "cancelled"
    elif counts.get("pending") or counts.get("processing"):
        job["status"] = "processing"
    else:
        job["status"] = "completed"
    job["finished_at"] = _now()


def _process_item(job: dict, item: dict) -> None:
    job_id = job["id"]
    item_id = item["id"]
    orig_path = JOBS_DIR / job_id / "items" / item_id / "original.bin"
    t0 = _now()
    log.info("Image processing started job=%s item=%s", job_id, item_id)

    def progress(pct: int, stage: str) -> None:
        with _lock:
            if item["status"] == "processing":
                item["progress"] = max(0, min(100, pct))
                item["stage"] = stage

    try:
        if job.get("cancel"):
            with _lock:
                item["status"] = "cancelled"
                item["error"] = "Processing was cancelled."
                item["stage"] = "cancelled"
            return
        data = orig_path.read_bytes()
        cfg = job.get("settings") or default_settings()
        jpeg, info, final_img = process_image(
            data,
            progress=progress,
            scale=int(cfg.get("upscale_factor") or 4),
            min_bytes=int(cfg.get("min_output_bytes") or 0),
            max_bytes=cfg.get("max_output_bytes"),
        )
        preview = make_preview_jpeg(final_img)
        d = _item_dir(job_id, item_id)
        used = job.setdefault("used_names", set())
        out_name = unique_label(f"{_safe_stem(item['filename'])}-upscaled.jpg", used)
        (d / "result.jpg").write_bytes(jpeg)
        (d / "result_preview.jpg").write_bytes(preview)
        with _lock:
            item["status"] = "completed"
            item["progress"] = 100
            item["stage"] = "done"
            item["error"] = None
            item["output_name"] = out_name
            item["output"] = {
                "width": info["output_width"],
                "height": info["output_height"],
                "format": "JPEG",
                "size": info["output_size"],
                "scale": info["scale"],
                "backend": info["backend"],
            }
            item["finished_at"] = _now()
            elapsed = item["finished_at"] - t0
            job.setdefault("times", []).append(elapsed)
            times = job["times"][-8:]
            job["avg_seconds"] = sum(times) / len(times)
        log.info("Image processing completed job=%s item=%s bytes=%s", job_id, item_id, info["output_size"])
    except AppError as exc:
        log.info("Image processing failed job=%s item=%s code=%s", job_id, item_id, exc.code)
        with _lock:
            item["status"] = "failed"
            item["error"] = exc.message
            item["stage"] = "failed"
            item["progress"] = 0
            item["finished_at"] = _now()
    except Exception:
        log.exception("Image processing failed job=%s item=%s", job_id, item_id)
        with _lock:
            item["status"] = "failed"
            item["error"] = "We couldn't process this image."
            item["stage"] = "failed"
            item["progress"] = 0
            item["finished_at"] = _now()


def result_path(job_id: str, item_id: str) -> Path:
    job = get_job(job_id)
    item = get_item(job, item_id)
    path = JOBS_DIR / job_id / "items" / item_id / "result.jpg"
    if item["status"] != "completed" or not path.exists():
        raise AppError("not_ready", "The file is not ready to download yet.", 404)
    return path


def preview_path(job_id: str, item_id: str, which: str) -> Path:
    get_job(job_id)
    get_item(get_job(job_id), item_id)
    d = JOBS_DIR / job_id / "items" / item_id
    if which == "result":
        path = d / "result_preview.jpg"
    else:
        path = d / "preview.jpg"
    if not path.exists():
        raise AppError("not_ready", "No preview is available yet.", 404)
    return path


def build_zip(job_id: str, item_ids: Optional[list[str]] = None) -> tuple[bytes, str]:
    job = get_job(job_id)
    entries = []
    for it in job["items"]:
        if it["status"] != "completed":
            continue
        if item_ids is not None and it["id"] not in item_ids:
            continue
        path = JOBS_DIR / job_id / "items" / it["id"] / "result.jpg"
        if path.exists():
            entries.append((it.get("output_name") or f"{it['filename']}-upscaled.jpg", path.read_bytes()))
    if not entries:
        raise AppError("not_ready", "No completed images to download.", 404)
    return write_zip(entries), "upscaled-images.zip"


def cleanup_expired(now: Optional[float] = None) -> int:
    now = now or _now()
    removed = 0
    with _lock:
        expired = [
            jid
            for jid, job in _jobs.items()
            if now - job["created_at"] > JOB_TTL_SECONDS and not job.get("running")
        ]
    for jid in expired:
        delete_job(jid)
        removed += 1
    # Orphan directories (process restart)
    if JOBS_DIR.exists():
        known = set(_jobs.keys())
        for child in JOBS_DIR.iterdir():
            if child.is_dir() and child.name not in known:
                age = now - child.stat().st_mtime
                if age > JOB_TTL_SECONDS:
                    shutil.rmtree(child, ignore_errors=True)
                    removed += 1
                    log.info("Cleanup completed orphan=%s", child.name)
    return removed


def check_upload_size(filename: str, size: int) -> None:
    suffix = Path(filename).suffix.lower()
    limit = MAX_ZIP_SIZE if suffix == ".zip" else MAX_UPLOAD_SIZE
    if size > limit:
        raise AppError("too_large", "This file exceeds the maximum upload size.")
