"""Builds every LenDen Saathi icon and logo file from the owner's original logo (brand/lenden-saathi-logo-original.webp).

    python brand/make_assets.py

The original is a rounded blue tile on a white background. This script
  1. cuts the tile out (the white OUTSIDE the tile becomes transparent; white parts INSIDE the logo are kept),
  2. writes the phone app icons (icon, Android adaptive foreground + background, splash, favicon),
  3. writes the website logo and favicon.
Re-run it after replacing the original file; nothing else needs editing.
"""
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "brand" / "lenden-saathi-logo-original.webp"
TOP, BOTTOM = (0, 77, 188), (0, 18, 83)          # the tile's gradient, sampled from the original
SPLASH_BG = "#001A7D"


def _outside_region(candidate: np.ndarray) -> np.ndarray:
    """Pixels of `candidate` (True = near white) that are connected to the image corners (4-connected flood fill)."""
    from collections import deque
    h, w = candidate.shape
    seen = np.zeros_like(candidate, dtype=bool)
    q = deque()
    for y, x in ((2, 2), (2, w - 3), (h - 3, 2), (h - 3, w - 3)):
        if candidate[y, x] and not seen[y, x]:
            seen[y, x] = True
            q.append((y, x))
    while q:
        y, x = q.popleft()
        for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
            if 0 <= ny < h and 0 <= nx < w and candidate[ny, nx] and not seen[ny, nx]:
                seen[ny, nx] = True
                q.append((ny, nx))
    return seen


def cut_out_tile(img: Image.Image) -> Image.Image:
    """RGBA tile with transparent surroundings, cropped square. White INSIDE the logo is kept."""
    rgb = img.convert("RGB")
    a = np.array(rgb).astype(int)
    outside = _outside_region(a.min(axis=2) >= 225)
    alpha = Image.fromarray(np.where(outside, 0, 255).astype(np.uint8), "L")
    alpha = alpha.filter(ImageFilter.MinFilter(5)).filter(ImageFilter.GaussianBlur(1.4))   # trim the white fringe, soften the edge
    out = rgb.convert("RGBA")
    out.putalpha(alpha)
    box = out.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
    out = out.crop(box)
    side = max(out.size)
    sq = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    sq.paste(out, ((side - out.width) // 2, (side - out.height) // 2))
    return sq


def gradient(size: int, top_y: int = 0, bottom_y: int | None = None) -> Image.Image:
    """Vertical blue gradient that equals the tile's top colour above top_y and its bottom colour below bottom_y."""
    bottom_y = size if bottom_y is None else bottom_y
    ys = np.clip((np.arange(size) - top_y) / max(1, bottom_y - top_y), 0, 1)[:, None, None]
    arr = (np.array(TOP) * (1 - ys) + np.array(BOTTOM) * ys).astype(np.uint8)
    arr = np.repeat(arr, size, axis=1)
    return Image.fromarray(arr, "RGB").convert("RGBA")


def fit(tile: Image.Image, px: int) -> Image.Image:
    return tile.resize((px, px), Image.LANCZOS)


def canvas_with(tile: Image.Image, canvas: int, tile_px: int, background: Image.Image | None) -> Image.Image:
    base = background.copy() if background else Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    off = (canvas - tile_px) // 2
    base.alpha_composite(fit(tile, tile_px), (off, off))
    return base


def save(img: Image.Image, rel: str) -> None:
    p = ROOT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    img.save(p)
    print("wrote", rel, img.size)


def main() -> None:
    tile = cut_out_tile(Image.open(SRC))
    save(fit(tile, 1024), "brand/lenden-saathi-logo.png")

    # phone app. The icon fills the square: the tile on a gradient that matches it, so the rounded corners disappear.
    save(canvas_with(tile, 1024, 1024, gradient(1024)), "mobile/assets/icon.png")
    # Android adaptive icon: the logo sits inside the safe circle; the background gradient meets the tile's own colours
    tile_px = 660
    off = (1024 - tile_px) // 2
    save(gradient(1024, off, off + tile_px), "mobile/assets/android-icon-background.png")
    save(canvas_with(tile, 1024, tile_px, None), "mobile/assets/android-icon-foreground.png")
    save(canvas_with(tile, 1024, 900, None), "mobile/assets/splash-icon.png")
    save(fit(tile, 48), "mobile/assets/favicon.png")

    # website
    save(fit(tile, 512), "backend/static/img/logo.png")
    save(fit(tile, 64), "backend/static/img/favicon.png")


if __name__ == "__main__":
    main()
