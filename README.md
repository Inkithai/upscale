# AI Image Upscaler

A small production-style web app that **4× AI-upscales** images and exports **real JPEG files of at least 4 MB**.

Upload one photo or a ZIP of many. Each image is validated, oriented, upscaled, encoded as JPEG, and queued independently so one failure never kills the batch.

```
UPLOAD → VALIDATE → QUEUE → 4× AI UPSCALING → JPEG ≥ 4 MB → COMPARE → DOWNLOAD
```

## Features

- Single image upload (drag & drop, file picker, or paste a screenshot)
- ZIP upload with nested folders
- 4× AI super-resolution (OpenCV **ESPCN x4** on CPU)
- Every successful output is `image/jpeg` and **≥ 4 MB** (no dummy file padding)
- Per-image status, progress, retry, and cancel
- Partial batch failure: download what worked, retry what did not
- Before/after slider (mouse, touch, keyboard)
- Individual JPEG download and `upscaled-images.zip`
- EXIF orientation correction for phone photos
- Transparent PNG/WebP composited onto a configurable background (default **white**)
- Safe ZIP extraction (Zip Slip, zip bombs, junk files)
- Health check, structured errors, TTL cleanup of temp files

## Supported formats

| Input | Output |
| --- | --- |
| JPG, JPEG, PNG, WebP | JPEG (`image/jpeg`, ≥ 4 MB) |
| ZIP of the above | ZIP of JPEGs |

Harmless extras inside ZIPs (`.DS_Store`, `Thumbs.db`, `__MACOSX/`) are ignored.

## Upload methods

- Drag & drop an image or ZIP
- **Choose image** / **Choose ZIP**
- Paste from the clipboard (screenshots)

After upload you see filename, size, dimensions, format, and validation status. Remove files, process the queue, cancel, or retry without re-uploading.

## 4× AI upscaling

The **web app** uses OpenCV DNN **ESPCN x4**. That is real 4× super-resolution, chosen because it runs on CPU-only free hosts.

If the ESPCN weights cannot be downloaded, the server falls back to cubic resize + unsharp mask and still scales **4×**. `/health` reports `"model": "espcn"` or `"model": "fallback"`.

The **Colab notebook** is a separate GPU implementation (Real-ESRGAN via [spandrel](https://github.com/chaiNNer-org/spandrel)). It is not used by this web app.

## 4 MB JPEG requirement

4× resolution alone does not guarantee a 4 MB file. After upscaling the encoder:

1. Writes a high-quality 4:4:4 JPEG
2. Raises quality to 100 if needed
3. Enlarges with LANCZOS if the file is still under 4 MB
4. As a last resort, adds light photographic grain (still a real image)

It does **not** append JPEG comment markers or trailing zeros. If a file still cannot reach 4 MB without exceeding `MAX_OUTPUT_PIXELS`, that item **fails** instead of returning a padded fake.

## Transparency

JPEG has no alpha channel. Transparent pixels are composited onto `TRANSPARENCY_BG` (default `#FFFFFF`) so you do not get a black matte.

## Bulk ZIP processing

Example layout:

```text
images.zip
 ├── photo1.jpg
 ├── photo2.png
 ├── photo3.webp
 └── folder/photo4.jpg
```

Duplicate names become `photo.jpg`, `photo_1.jpg`, … Output names are `{stem}-upscaled.jpg`. The download archive is always `upscaled-images.zip`.

## Installation

Python 3.11+ recommended.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Local development

```bash
PYTHONPATH=. uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

```bash
PYTHONPATH=. pytest
```

## Environment variables

See [`.env.example`](.env.example). Important knobs:

| Variable | Default | Meaning |
| --- | --- | --- |
| `MAX_UPLOAD_SIZE` | 80 MB | Max single image |
| `MAX_ZIP_SIZE` | 200 MB | Max ZIP upload |
| `MAX_IMAGES_PER_BATCH` | 80 | Max images per job |
| `MAX_EXTRACTED_SIZE` | 400 MB | Max decompressed ZIP bytes |
| `MAX_IMAGE_PIXELS` | 12 MP | Max input pixels |
| `MIN_OUTPUT_SIZE_MB` | 4.0 | Hard JPEG floor |
| `UPSCALE_FACTOR` | 4 | Super-resolution factor |
| `JPEG_QUALITY` | 95 | Starting JPEG quality |
| `MAX_CONCURRENT_JOBS` | 1 | Parallel jobs (keep low on CPU) |
| `TRANSPARENCY_BG` | `#FFFFFF` | Alpha composite color |
| `UPSCALE_BACKEND` | `auto` | `auto`, `espcn`, or `cubic` |
| `JOB_TTL_SECONDS` | 3600 | When job files are deleted |

Copy `.env.example` to `.env` if you want a file-based config. Do not commit secrets (this app has none by default).

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | `{ "status": "ok" }` |
| `GET` | `/api/config` | Public limits for the UI |
| `POST` | `/api/jobs` | Multipart `files` (images and/or ZIPs) |
| `GET` | `/api/jobs/{id}` | Queue + per-image status |
| `POST` | `/api/jobs/{id}/process` | Start pending items |
| `POST` | `/api/jobs/{id}/cancel` | Stop queued work; keep completed |
| `POST` | `/api/jobs/{id}/retry-failed` | Retry failures without re-upload |
| `POST` | `/api/jobs/{id}/items/{item}/retry` | Retry one image |
| `GET` | `/api/jobs/{id}/items/{item}/file` | Download JPEG |
| `GET` | `/api/jobs/{id}/zip` | All completed as `upscaled-images.zip` |
| `POST` | `/api/jobs/{id}/zip` | Selected items `{ "item_ids": [...] }` |
| `DELETE` | `/api/jobs/{id}` | Delete job and temp files |

Errors look like:

```json
{ "error": { "code": "invalid_image", "message": "This file doesn't look like a valid image." } }
```

Stack traces are never sent to the client.

## Deployment

This is a Python CPU app with uploads. **Do not put the API on Vercel/Netlify.**

### Docker

```bash
docker build -t upscaler .
docker run -p 8000:8000 upscaler
```

### Hugging Face Spaces / Render / Railway / Fly.io

Use the included `Dockerfile`. Set the platform port to **8000** (or `PORT`). Free CPU tiers sleep, have no GPU, and ephemeral disks — processed files disappear on restart.

Keep `MAX_CONCURRENT_JOBS=1` on small hosts.

## Google Colab

[`colab/AI_Image_Upscaler.ipynb`](colab/AI_Image_Upscaler.ipynb) is the **reference GPU notebook**. It is intentionally independent of this web app:

1. Runtime → GPU
2. Run all cells
3. Upload an image or ZIP
4. Download JPEGs or `all_upscaled_images.zip`

It uses Colab’s PyTorch plus **spandrel** (Real-ESRGAN x4). Do not swap it for BasicSR / GFPGAN.

## Limitations

- CPU ESPCN is slower and softer than Colab Real-ESRGAN on GPU
- Very large inputs are rejected (`MAX_IMAGE_PIXELS`) so the process does not OOM
- Extremely simple graphics (a 2×2 flat color) may fail the 4 MB rule if enlargement would exceed `MAX_OUTPUT_PIXELS`
- Jobs live in local disk and memory — no Redis, database, or accounts
- Previews are downscaled; downloads are the full JPEG

## Troubleshooting

| Symptom | What to try |
| --- | --- |
| `/health` says `"fallback"` | The ESPCN `.pb` weights could not be downloaded. Check outbound HTTPS to GitHub. |
| Upload rejected | Confirm JPG/PNG/WebP/ZIP and the size limits in `/api/config`. |
| ZIP rejected | Nested `..` paths, zip bombs, or no images inside. |
| Image rotated wrong | File may lack EXIF; we only correct tagged orientation. |
| Black PNG background | Set `TRANSPARENCY_BG=#FFFFFF` (the default). |
| Disk filling up | Jobs are deleted after `JOB_TTL_SECONDS`. Restart also wipes `jobs/`. |
| Host runs out of RAM | Lower `MAX_IMAGE_PIXELS`, `MAX_IMAGES_PER_BATCH`, and `MAX_CONCURRENT_JOBS`. |

## Project layout

```text
backend/     FastAPI app, queue, validation, ESPCN, JPEG encoder
frontend/    Single-page UI (HTML/CSS/JS)
colab/       Reference notebook (do not treat as the web backend)
tests/       Pytest coverage for images, ZIPs, API, and security
```
