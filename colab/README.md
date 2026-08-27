# Colab notebook

This folder holds the **reference GPU implementation**. The web app in `../backend` does not import it.

Open [`AI_Image_Upscaler.ipynb`](AI_Image_Upscaler.ipynb) in [Google Colab](https://colab.research.google.com/).

1. Runtime → Change runtime type → **GPU**
2. Run all cells
3. Upload one image (JPG/PNG/WebP) or a ZIP
4. Download each JPEG or `all_upscaled_images.zip`

Uses **spandrel** + Colab’s bundled PyTorch. Avoids deprecated BasicSR / GFPGAN / `realesrgan` PyPI installs.
