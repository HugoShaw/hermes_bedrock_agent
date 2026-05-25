"""PIL image operations: tiling, stitching, resizing."""

from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path
from typing import Optional

from PIL import Image

# Allow very large images (Excel renders can be huge)
Image.MAX_IMAGE_PIXELS = 500_000_000


def load_image(path: str) -> Image.Image:
    img = Image.open(path)
    img.load()
    return img


def resize_to_max(img: Image.Image, max_dim: int) -> Image.Image:
    """Proportionally resize so the longest edge ≤ max_dim. Returns a new image."""
    w, h = img.size
    if max(w, h) <= max_dim:
        return img.copy()
    ratio = max_dim / max(w, h)
    return img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)


def to_png_bytes(img: Image.Image, max_bytes: int = 4_500_000) -> tuple[bytes, str]:
    """Encode image to PNG bytes. Falls back to JPEG if PNG exceeds max_bytes.

    Returns (raw_bytes, media_type).
    """
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
    """Load an image, resize if needed, return (bytes, media_type) ready for Bedrock."""
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
    """Tile a large image into overlapping sub-images.

    Writes PNG files to output_dir (or a temp dir if empty).
    Returns list of file paths sorted row-major (r00_c00, r00_c01, …).
    """
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
            x2 = min(x + tile_size, w)
            y2 = min(y + tile_size, h)
            tile = img.crop((x, y, x2, y2))
            fname = f"{prefix}_r{row:02d}_c{col:02d}.png"
            out_path = os.path.join(output_dir, fname)
            tile.save(out_path, format="PNG")
            paths.append(out_path)
            col += 1
            x += step
        row += 1
        y += step

    return sorted(paths)


def stitch_tiles(
    tile_paths: list[str],
    original_size: tuple[int, int],
    tile_size: int = 3000,
    overlap: int = 300,
) -> Image.Image:
    """Reconstruct a full image from tiles (for QA / review purposes)."""
    canvas = Image.new("RGB", original_size, color=(255, 255, 255))
    step = tile_size - overlap

    for path in sorted(tile_paths):
        fname = Path(path).stem  # e.g. tile_r01_c02
        parts = fname.split("_")
        row = int(parts[-2][1:])
        col = int(parts[-1][1:])
        tile = Image.open(path)
        x = col * step
        y = row * step
        canvas.paste(tile, (x, y))

    return canvas


def needs_tiling(img: Image.Image, max_dim: int = 4000) -> bool:
    """True if either image dimension exceeds max_dim."""
    return max(img.size) > max_dim
