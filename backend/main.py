from __future__ import annotations

import io
import shutil
import threading
import uuid
import zipfile
from pathlib import Path
from typing import Dict, List

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware

from backend.upscale import process_image_bytes

ROOT = Path(__file__).resolve().parent.parent
JOBS = ROOT / "jobs"
JOBS.mkdir(exist_ok=True)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}

app = FastAPI(title="AI Image Upscaler")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

jobs: Dict[str, dict] = {}


def _safe_name(name: str) -> str:
    base = Path(name).name
    return base.replace("..", "_") or "image"


@app.get("/", response_class=HTMLResponse)
def index():
    return (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    job_id = uuid.uuid4().hex[:12]
    work = JOBS / job_id
    inp = work / "input"
    out = work / "output"
    inp.mkdir(parents=True)
    out.mkdir(parents=True)

    raw = await file.read()
    fname = _safe_name(file.filename or "upload.bin")
    dest = work / fname
    dest.write_bytes(raw)

    images: List[Path] = []
    suffix = Path(fname).suffix.lower()
    if suffix == ".zip":
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                zf.extractall(inp)
        except zipfile.BadZipFile:
            shutil.rmtree(work, ignore_errors=True)
            raise HTTPException(400, "Not a valid ZIP file.")
        for p in inp.rglob("*"):
            if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
                images.append(p)
    elif suffix in IMAGE_EXTS:
        target = inp / fname
        target.write_bytes(raw)
        images.append(target)
    else:
        shutil.rmtree(work, ignore_errors=True)
        raise HTTPException(
            400,
            "Upload a JPG, PNG, WebP image or a ZIP of images.",
        )

    if not images:
        shutil.rmtree(work, ignore_errors=True)
        raise HTTPException(400, "No supported images found (JPG, PNG, WebP).")

    jobs[job_id] = {
        "status": "queued",
        "total": len(images),
        "done": 0,
        "current": "",
        "outputs": [],
        "error": None,
        "work": str(work),
        "images": [str(p) for p in images],
    }
    return {"job_id": job_id, "total": len(images)}


@app.post("/api/process/{job_id}")
def process(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Unknown job")
    if job["status"] == "done":
        return job_public(job)
    job["status"] = "processing"
    out_dir = Path(job["work"]) / "output"
    outputs = []
    try:
        for i, path_s in enumerate(job["images"]):
            path = Path(path_s)
            job["current"] = path.name
            job["done"] = i
            data = path.read_bytes()
            jpeg = process_image_bytes(data)
            out_name = f"{path.stem}_upscaled.jpg"
            out_path = out_dir / out_name
            # avoid collisions
            n = 1
            while out_path.exists():
                out_name = f"{path.stem}_upscaled_{n}.jpg"
                out_path = out_dir / out_name
                n += 1
            out_path.write_bytes(jpeg)
            outputs.append(
                {
                    "name": out_name,
                    "size": len(jpeg),
                    "url": f"/api/jobs/{job_id}/file/{out_name}",
                }
            )
            job["outputs"] = outputs
            job["done"] = i + 1
        job["status"] = "done"
        job["current"] = ""
        # zip all
        zip_path = Path(job["work"]) / "all_upscaled_images.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for o in outputs:
                zf.write(out_dir / o["name"], o["name"])
        job["zip_url"] = f"/api/jobs/{job_id}/zip"
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)
        raise
    return job_public(job)


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Unknown job")
    return job_public(job)


@app.get("/api/jobs/{job_id}/file/{name}")
def job_file(job_id: str, name: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Unknown job")
    path = Path(job["work"]) / "output" / Path(name).name
    if not path.exists():
        raise HTTPException(404, "File not found")
    return FileResponse(path, media_type="image/jpeg", filename=path.name)


@app.get("/api/jobs/{job_id}/zip")
def job_zip(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Unknown job")
    path = Path(job["work"]) / "all_upscaled_images.zip"
    if not path.exists():
        raise HTTPException(404, "ZIP not ready")
    return FileResponse(
        path, media_type="application/zip", filename="all_upscaled_images.zip"
    )


def job_public(job: dict) -> dict:
    return {
        "status": job["status"],
        "total": job["total"],
        "done": job["done"],
        "current": job["current"],
        "outputs": job.get("outputs", []),
        "error": job.get("error"),
        "zip_url": job.get("zip_url"),
    }


static = ROOT / "frontend"
if static.exists():
    app.mount("/static", StaticFiles(directory=static), name="static")
