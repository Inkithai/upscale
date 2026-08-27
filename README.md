# AI Image Upscaler

Web app (from the original Colab notebook) that AI-upscales images 4× with ESPCN and exports JPEG files of at least 4 MB.

## Features

- Single image upload (JPG, PNG, WebP)
- ZIP of many images
- 4× AI super-resolution
- JPEG output ≥ 4 MB each
- Per-image download and ZIP of all results
- Upload and processing progress

## Google Colab

Use [`colab/AI_Image_Upscaler.ipynb`](colab/AI_Image_Upscaler.ipynb): GPU runtime, upload a photo or ZIP, download JPEGs (≥ 4 MB) or a ZIP of everything. Current stack: Colab PyTorch + [spandrel](https://github.com/chaiNNer-org/spandrel) (no BasicSR/GFPGAN).

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=. uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

## Deploy for free

This is a Python CPU app with file uploads. **Do not use Vercel/Netlify** for the API — they are for static/serverless frontends.

### 1. Hugging Face Spaces (easiest free option)

1. Create a free account at [huggingface.co](https://huggingface.co)
2. **New Space** → SDK: **Docker** → hardware: **CPU basic** (free)
3. Push this repo into the Space (or upload `Dockerfile`, `requirements.txt`, `backend/`, `frontend/`)
4. In Space settings, if the UI does not load, set the app port to **8000**

Spaces sleep after inactivity on the free CPU tier; the first request can take a minute to wake.

### 2. Render (free web service)

1. Push the repo to GitHub
2. [dashboard.render.com](https://dashboard.render.com) → **New Web Service** → connect the repo
3. Runtime: Docker, or:
   - Build: `pip install -r requirements.txt`
   - Start: `PYTHONPATH=. uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
4. Free instances **spin down** after ~15 minutes idle

### 3. Railway / Fly.io

Both have a small free credit each month. Deploy the same Docker image. Set `PORT` from the platform.

### 4. Keep using Colab (zero hosting)

The original notebook `zipupscaylbyinki (1).ipynb` still runs on **Google Colab** with a free GPU. Best if you only need this yourself, not a public URL.

### Limits on free tiers

- Sleep / cold start
- CPU only (upscale is slower than a GPU)
- Disk is ephemeral — processed files disappear when the instance restarts
- Upload size caps (often 100 MB or less)

For a public product, a cheap always-on VPS (~$4–6/month) is more reliable than free sleep-tier hosts.
