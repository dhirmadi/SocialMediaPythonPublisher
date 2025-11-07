from __future__ import annotations

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


