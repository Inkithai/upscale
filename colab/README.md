# Colab notebook

This folder holds the **reference GPU implementation**. The web app in `../backend` does not import it.

Open [`AI_Image_Upscaler.ipynb`](AI_Image_Upscaler.ipynb) in [Google Colab](https://colab.research.google.com/).

1. Runtime → Change runtime type → **GPU**
2. Run all cells
3. Upload one image (JPG/PNG/WebP) or a ZIP
4. Export in the last cell — set `EXPORT_METHOD`:
   * `"drive"` (default, fastest for batches) → files are copied to
     `MyDrive/upscaled_images`, download from the Drive web UI in parallel
   * `"serve"` → starts `http.server` on port 8080; use Colab's **Ports** tab to
     grab split ZIPs over direct HTTPS (fast, resumable)
   * `"zip_browser"` → the old `files.download()` path, ~1–3 MB/s. Keep the tab focused.

Uses **spandrel** + Colab’s bundled PyTorch. Avoids deprecated BasicSR / GFPGAN / `realesrgan` PyPI installs.

## Why `files.download()` is slow

* It is **not** an HTTP download: bytes travel kernel → websocket → browser, single
  stream, no resume, throttled to ~1–3 MB/s and paused whenever the tab loses focus.
* Large single files go through a blob URL; Chrome can run out of memory and fail the
  download silently above a few hundred MB.
* The ZIP used `ZIP_DEFLATED`, which re-compresses quality-100 JPEGs for ~0% savings.
* Downloading every image *and* the ZIP moved the whole batch twice.
* Full-size inline previews add MBs of base64 per cell — that also makes
  **File → Download → `.ipynb`** slow. Clear outputs (Edit → Clear all outputs) first,
  or use *Save a copy in GitHub* and fetch the raw file.

JPEGs are already compressed: export now uses `ZIP_STORED` (~20× faster to pack,
identical size) and splits archives at 400 MB so one failure costs little.
