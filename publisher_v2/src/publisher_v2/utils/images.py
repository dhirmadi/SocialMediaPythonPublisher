"""Pillow-backed image helpers: resizing and width capping for publishing.

Sets the process-wide decompression-bomb ceiling (#90/SEC-6) as an import side
effect, so this module must be imported before untrusted image bytes are
decoded.
"""

import shutil
from io import BytesIO

from PIL import Image, ImageOps

# #90 (SEC-6): global Pillow decompression-bomb ceiling. Pillow raises
# DecompressionBombError above 2x this pixel count; upload maps it to 415,
# the thumbnail path to 422.
Image.MAX_IMAGE_PIXELS = 40_000_000


def resize_image_bytes(data: bytes, max_dimension: int, quality: int = 85) -> bytes:
    """Resize image bytes so the longest side is <= max_dimension. Returns JPEG bytes.

    - Preserves aspect ratio with LANCZOS resampling.
    - Does NOT upscale images already smaller than max_dimension; they are still
      re-encoded as JPEG for downstream consistency (PUB-041 AC-04).
    - Non-RGB modes (RGBA, P, LA, etc.) are converted to RGB before JPEG encoding.
    """
    src = Image.open(BytesIO(data))
    img: Image.Image = src.convert("RGB") if src.mode != "RGB" else src

    w, h = img.size
    if max_dimension > 0 and max(w, h) > max_dimension:
        scale = max_dimension / max(w, h)
        new_w = max(1, round(w * scale))
        new_h = max(1, round(h * scale))
        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

    buf = BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def ensure_max_width(image_path: str, max_width: int = 1280, out_path: str | None = None, quality: int = 90) -> str:
    """Ensure the image is at most ``max_width`` pixels wide (#83).

    When ``out_path`` is given, the result is written there and the source file
    is NEVER modified (a straight copy when no resize is needed, so a variant
    path always exists). Without ``out_path`` the legacy in-place behavior is
    kept. EXIF orientation is applied before resizing so rotated phone photos
    don't come out sideways.
    """
    with Image.open(image_path) as img:
        oriented = ImageOps.exif_transpose(img) or img
        width, height = oriented.size
        if width <= max_width:
            if out_path and out_path != image_path:
                shutil.copyfile(image_path, out_path)
                return out_path
            return image_path
        new_height = int((max_width / width) * height)
        resized = oriented.resize((max_width, new_height), Image.Resampling.LANCZOS)
        target = out_path or image_path
        resized.save(target, quality=quality)
        return target
