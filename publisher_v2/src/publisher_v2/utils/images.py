import asyncio
from io import BytesIO

from PIL import Image


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


def ensure_max_width(image_path: str, max_width: int = 1280) -> str:
    with Image.open(image_path) as img:
        width, height = img.size
        if width <= max_width:
            return image_path
        new_height = int((max_width / width) * height)
        resized = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
        out_path = image_path
        resized.save(out_path)
        return out_path


async def ensure_max_width_async(image_path: str, max_width: int = 1280) -> str:
    """
    Async helper that ensures the image does not exceed max_width by delegating
    to the synchronous ensure_max_width implementation in a thread pool.
    """

    return await asyncio.to_thread(ensure_max_width, image_path, max_width)
