"""PIL image operations: tiling, stitching, resizing."""

from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path

from PIL import Image

# Allow very large images (Excel renders can be huge)
Image.MAX_IMAGE_PIXELS = 500_000_000


def load_image(path: str) -> Image.Image:
    img = Image.open(path)
    img.load()
    return img


def resize_to_max(img: Image.Image, max_dim: int) -> Image.Image:
    w, h = img.size
    if max(w, h) <= max_dim:
        return img.copy()
    ratio = max_dim / max(w, h)
    return img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)


def to_png_bytes(img: Image.Image, max_bytes: int = 4_500_000) -> tuple[bytes, str]:
    """Encode to PNG; fall back to JPEG if PNG exceeds max_bytes. Returns (bytes, media_type)."""
    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    png_bytes = buf.getvalue()
    if len(png_bytes) <= max_bytes:
        return png_bytes, "image/png"
    buf = BytesIO()
    rgb = img.convert("RGB") if img.mode == "RGBA" else img
    rgb.save(buf, format="JPEG", quality=85)
    return buf.getvalue(), "image/jpeg"


def load_for_vlm(path: str, max_dim: int = 7900, max_bytes: int = 4_500_000) -> tuple[bytes, str]:
    """Load, resize if needed, return (bytes, media_type) for Bedrock."""
    img = load_image(path)
    img = resize_to_max(img, max_dim)
    return to_png_bytes(img, max_bytes)


def generate_tiles(
    img: Image.Image,
    tile_size: int = 3000,
    overlap: int = 300,
    output_dir: str = "",
    prefix: str = "tile",
) -> list[str]:
    """Tile a large image into overlapping sub-images. Returns sorted file paths."""
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    else:
        import tempfile
        output_dir = tempfile.mkdtemp()

    w, h = img.size
    step = tile_size - overlap
    paths: list[str] = []
    row = 0
    y = 0
    while y < h:
        col = 0
        x = 0
        while x < w:
            tile = img.crop((x, y, min(x + tile_size, w), min(y + tile_size, h)))
            fname = f"{prefix}_r{row:02d}_c{col:02d}.png"
            out_path = os.path.join(output_dir, fname)
            tile.save(out_path, format="PNG")
            paths.append(out_path)
            col += 1
            x += step
        row += 1
        y += step

    return sorted(paths)


def needs_tiling(img: Image.Image, max_dim: int = 4000) -> bool:
    return max(img.size) > max_dim
