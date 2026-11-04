"""Generates every UdhaarSaathi logo file from one definition: the 'Hisaab tally' mark.

    python brand/make_logo.py

Mark: four cream bars (the shopkeeper's tally) crossed by a gold slash (the account is settled).
Geometry is defined once on a 140 x 140 grid and drawn at 4x then reduced, so edges stay clean at every size.
"""
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
GREEN, CREAM, GOLD, GOLD_DARK = (11, 110, 79), (255, 248, 231), (242, 169, 0), (196, 130, 0)
BARS = [(32, 30, 43, 110), (52, 30, 63, 110), (72, 30, 83, 110), (92, 30, 103, 110)]   # x0, y0, x1, y1
SLASH = ((20, 98), (120, 42), 11)                                                        # p0, p1, width
HALO = 3                                                                                 # gap between slash and bars
SS = 4


def mark_layer(size: int, u: float, bar_rgb, slash_rgb, knockout=True) -> Image.Image:
    """The mark centred on a transparent size x size canvas. u = pixels per grid unit."""
    s = size * SS
    k = u * SS
    c = s / 2 - 70 * k                                   # offset so grid point (70, 70) lands on the canvas centre

    def P(x, y):
        return (c + x * k, c + y * k)

    def stroke(draw, fill, extra=0):
        (x0, y0), (x1, y1), w = SLASH
        w = (w + extra) * k
        a, b = P(x0, y0), P(x1, y1)
        draw.line([a, b], fill=fill, width=int(w))
        for cx, cy in (a, b):
            draw.ellipse([cx - w / 2, cy - w / 2, cx + w / 2, cy + w / 2], fill=fill)

    bars = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(bars)
    for x0, y0, x1, y1 in BARS:
        d.rounded_rectangle([*P(x0, y0), *P(x1, y1)], radius=(x1 - x0) / 2 * k, fill=bar_rgb + (255,))
    if knockout:                                         # cut a clean gap around the slash (works on any background)
        halo = Image.new("L", (s, s), 0)
        stroke(ImageDraw.Draw(halo), 255, HALO * 2)
        bars.putalpha(ImageChops.multiply(bars.getchannel("A"), ImageChops.invert(halo)))
    slash = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    stroke(ImageDraw.Draw(slash), slash_rgb + (255,))
    bars.alpha_composite(slash)
    return bars.resize((size, size), Image.LANCZOS)


def tile(size: int, rounded=True, u_ratio=0.9) -> Image.Image:
    """Green app tile with the mark. u_ratio scales the mark relative to the tile."""
    s = size * SS
    base = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(base).rounded_rectangle([0, 0, s - 1, s - 1], radius=(s * 32 / 140) if rounded else 0, fill=GREEN + (255,))
    base = base.resize((size, size), Image.LANCZOS)
    base.alpha_composite(mark_layer(size, size / 140 * u_ratio, CREAM, GOLD))
    return base


def save(img: Image.Image, rel: str) -> None:
    p = ROOT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    img.save(p)
    print("wrote", rel, img.size)


def horizontal(height: int = 160) -> Image.Image:
    """Tile + 'UdhaarSaathi' wordmark on a transparent background (for light pages)."""
    font = ImageFont.truetype(r"C:\Windows\Fonts\segoeuib.ttf", int(height * 0.52))
    a, b = "Udhaar", "Saathi"
    wa, wb = font.getlength(a), font.getlength(b)
    gap = int(height * 0.2)
    img = Image.new("RGBA", (int(height + gap + wa + wb + height * 0.1), height), (0, 0, 0, 0))
    img.alpha_composite(tile(height))
    d = ImageDraw.Draw(img)
    y = height / 2
    d.text((height + gap, y), a, font=font, fill=GREEN + (255,), anchor="lm")
    d.text((height + gap + wa, y), b, font=font, fill=GOLD_DARK + (255,), anchor="lm")
    return img


SVG_MARK = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 140 140" role="img" aria-label="UdhaarSaathi">
  <title>UdhaarSaathi</title>
  <rect width="140" height="140" rx="32" fill="#0B6E4F"/>
  <g fill="#FFF8E7">
    <rect x="32" y="30" width="11" height="80" rx="5.5"/><rect x="52" y="30" width="11" height="80" rx="5.5"/>
    <rect x="72" y="30" width="11" height="80" rx="5.5"/><rect x="92" y="30" width="11" height="80" rx="5.5"/>
  </g>
  <path d="M20 98 L120 42" stroke="#0B6E4F" stroke-width="17" stroke-linecap="round"/>
  <path d="M20 98 L120 42" stroke="#F2A900" stroke-width="11" stroke-linecap="round"/>
</svg>
"""
SVG_HORIZONTAL = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 560 140" role="img" aria-label="UdhaarSaathi">
  <title>UdhaarSaathi</title>
  <rect width="140" height="140" rx="32" fill="#0B6E4F"/>
  <g fill="#FFF8E7">
    <rect x="32" y="30" width="11" height="80" rx="5.5"/><rect x="52" y="30" width="11" height="80" rx="5.5"/>
    <rect x="72" y="30" width="11" height="80" rx="5.5"/><rect x="92" y="30" width="11" height="80" rx="5.5"/>
  </g>
  <path d="M20 98 L120 42" stroke="#0B6E4F" stroke-width="17" stroke-linecap="round"/>
  <path d="M20 98 L120 42" stroke="#F2A900" stroke-width="11" stroke-linecap="round"/>
  <text x="170" y="92" font-family="'Segoe UI','Noto Sans',Arial,sans-serif" font-size="68" font-weight="700"><tspan fill="#0B6E4F">Udhaar</tspan><tspan fill="#C48200">Saathi</tspan></text>
</svg>
"""


def main() -> None:
    # phone app
    save(tile(1024, rounded=False, u_ratio=0.88).convert("RGBA"), "mobile/assets/icon.png")
    save(Image.new("RGBA", (1024, 1024), GREEN + (255,)), "mobile/assets/android-icon-background.png")
    save(mark_layer(1024, 4.8, CREAM, GOLD), "mobile/assets/android-icon-foreground.png")        # inside Android's safe circle
    save(mark_layer(1024, 4.8, (255, 255, 255), (255, 255, 255)), "mobile/assets/android-icon-monochrome.png")
    save(mark_layer(1024, 6.0, CREAM, GOLD), "mobile/assets/splash-icon.png")
    save(tile(48), "mobile/assets/favicon.png")
    # website
    save(tile(512), "backend/static/img/logo.png")
    save(tile(64), "backend/static/img/favicon.png")
    # brand kit
    save(tile(1024), "brand/logo-mark-1024.png")
    save(horizontal(), "brand/logo-horizontal.png")
    for name, svg in (("logo-mark.svg", SVG_MARK), ("logo-horizontal.svg", SVG_HORIZONTAL)):
        (ROOT / "brand" / name).write_text(svg, encoding="utf-8")
        print("wrote brand/" + name)
    (ROOT / "backend/static/img/logo.svg").write_text(SVG_MARK, encoding="utf-8")


if __name__ == "__main__":
    main()
