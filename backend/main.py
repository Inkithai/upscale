from __future__ import annotations

import logging
import threading
from typing import List

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware

from backend.config import (
    CLEANUP_INTERVAL_SECONDS,
    JOBS_DIR,
    LOG_LEVEL,
    MAX_UPLOAD_SIZE,
    MAX_ZIP_SIZE,
    ROOT,
    public_config,
)
from backend.errors import AppError, error_body
from backend.jobs import (
    build_zip,
    cancel_job,
    check_upload_size,
    cleanup_expired,
    create_job,
    delete_job,
    get_job,
    preview_path,
    public_job,
    remove_item,
    result_path,
    retry_items,
    start_processing,
)
from backend.upscale import model_status

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("upscale")

app = FastAPI(title="AI Image Upscaler", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND = ROOT / "frontend"
JOBS_DIR.mkdir(parents=True, exist_ok=True)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(status_code=exc.status_code, content=error_body(exc.code, exc.message))


@app.exception_handler(HTTPException)
async def http_err(request: Request, exc: HTTPException):
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    message = exc.detail if isinstance(exc.detail, str) else "Request failed."
    return JSONResponse(status_code=exc.status_code, content=error_body("http_error", message))


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("Unhandled error")
    return JSONResponse(
        status_code=500,
        content=error_body("internal", "Something went wrong. Please try again."),
    )


@app.middleware("http")
async def limit_content_length(request: Request, call_next):
    header = request.headers.get("content-length")
    if header:
        try:
            length = int(header)
        except ValueError:
            length = 0
        # Allow a little overhead over the larger of the two caps (ZIP).
        if length > max(MAX_UPLOAD_SIZE, MAX_ZIP_SIZE) + (2 * 1024 * 1024):
            return JSONResponse(
                status_code=413,
                content=error_body("too_large", "This file exceeds the maximum upload size."),
            )
    return await call_next(request)


def _cleanup_loop() -> None:
    while True:
        try:
            cleanup_expired()
        except Exception:
            log.exception("Cleanup failed")
        threading.Event().wait(CLEANUP_INTERVAL_SECONDS)


@app.on_event("startup")
def on_startup():
    log.info("Upload started listener ready")
    t = threading.Thread(target=_cleanup_loop, name="job-cleanup", daemon=True)
    t.start()


@app.get("/health")
def health():
    return {"status": "ok", "model": model_status()}


@app.get("/api/config")
def api_config():
    return public_config()


@app.get("/", response_class=HTMLResponse)
def index():
    return (FRONTEND / "index.html").read_text(encoding="utf-8")


@app.post("/api/jobs")
async def api_create_job(files: List[UploadFile] = File(...)):
    log.info("Upload started count=%s", len(files))
    payloads: list[tuple[str, bytes]] = []
    for upload in files:
        filename = upload.filename or "upload.bin"
        data = await upload.read()
        check_upload_size(filename, len(data))
        payloads.append((filename, data))
    job = create_job(payloads)
    return public_job(job)


@app.get("/api/jobs/{job_id}")
def api_job(job_id: str):
    return public_job(get_job(job_id))


@app.delete("/api/jobs/{job_id}")
def api_delete_job(job_id: str):
    delete_job(job_id)
    return {"ok": True}


@app.post("/api/jobs/{job_id}/process")
async def api_process(job_id: str, request: Request):
    body = {}
    if request.headers.get("content-type", "").startswith("application/json"):
        try:
            body = await request.json()
        except Exception:
            body = {}
    ids = body.get("item_ids") if isinstance(body, dict) else None
    job = start_processing(job_id, only_ids=ids)
    return public_job(job)


@app.post("/api/jobs/{job_id}/cancel")
def api_cancel(job_id: str):
    return public_job(cancel_job(job_id))


@app.post("/api/jobs/{job_id}/retry-failed")
def api_retry_failed(job_id: str):
    return public_job(retry_items(job_id))


@app.post("/api/jobs/{job_id}/items/{item_id}/retry")
def api_retry_item(job_id: str, item_id: str):
    return public_job(retry_items(job_id, item_ids=[item_id]))


@app.delete("/api/jobs/{job_id}/items/{item_id}")
def api_remove_item(job_id: str, item_id: str):
    return public_job(remove_item(job_id, item_id))


@app.get("/api/jobs/{job_id}/items/{item_id}/file")
def api_file(job_id: str, item_id: str):
    job = get_job(job_id)
    item = next((it for it in job["items"] if it["id"] == item_id), None)
    path = result_path(job_id, item_id)
    filename = (item or {}).get("output_name") or "upscaled.jpg"
    return FileResponse(path, media_type="image/jpeg", filename=filename)


@app.get("/api/jobs/{job_id}/items/{item_id}/preview")
def api_preview(job_id: str, item_id: str, which: str = "original"):
    path = preview_path(job_id, item_id, which)
    return FileResponse(path, media_type="image/jpeg")


@app.get("/api/jobs/{job_id}/zip")
def api_zip_all(job_id: str):
    data, name = build_zip(job_id)
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@app.post("/api/jobs/{job_id}/zip")
async def api_zip_selected(job_id: str, request: Request):
    body = {}
    try:
        body = await request.json()
    except Exception:
        body = {}
    ids = body.get("item_ids") if isinstance(body, dict) else None
    data, name = build_zip(job_id, item_ids=ids)
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


# Legacy routes kept so older clients still function.
@app.post("/api/upload")
async def legacy_upload(file: UploadFile = File(...)):
    data = await file.read()
    filename = file.filename or "upload.bin"
    check_upload_size(filename, len(data))
    job = create_job([(filename, data)])
    start_processing(job["id"])
    pub = public_job(job)
    pub["job_id"] = job["id"]
    pub["done"] = pub["counts"]["completed"]
    return pub


@app.post("/api/process/{job_id}")
def legacy_process(job_id: str):
    job = start_processing(job_id)
    pub = public_job(job)
    pub["job_id"] = job_id
    pub["done"] = pub["counts"]["completed"]
    pub["outputs"] = [
        {
            "name": it.get("download_name"),
            "size": (it.get("output") or {}).get("size"),
            "url": it.get("download_url"),
        }
        for it in pub["items"]
        if it["status"] == "completed"
    ]
    return pub


if FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND), name="static")
