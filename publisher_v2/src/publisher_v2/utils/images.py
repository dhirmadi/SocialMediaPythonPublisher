from __future__ import annotations

import asyncio

from PIL import Image


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

