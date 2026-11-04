"""Generates every UdhaarSaathi logo file from one definition: the 'Hisaab tally' mark.

    python brand/make_logo.py

Mark: four cream bars (the shopkeeper's tally) crossed by a gold slash (the account is settled).
Geometry is defined once on a 140 x 140 grid and drawn at 4x then reduced, so edges stay clean at every size.
"""
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
GREEN, CREAM, GOLD, GOLD_DARK = (11, 110, 79), (255, 248, 231), (242, 169, 0), (196, 130, 0)
# The mark: a rupee sign built from thick rounded strokes. Two cream bars (the tally strokes that make the rupee's top),
# a cream bowl, and a gold leg: the stroke that settles the account. All coordinates are on the 140 grid, stroke 11.
STROKE = 12
BARS = [((41, 30), (97, 30)), ((41, 54), (97, 54))]
BOWL = [(45, 30), (67, 30), (94, 30), (94, 74), (62, 74)]            # H then a cubic bezier: P0 .. P3 = (67,30) (94,30) (94,74) (62,74)
LEG = ((62, 74), (94, 112))
SS = 4


def _bezier(p0, p1, p2, p3, n=40):
    return [tuple((1 - t) ** 3 * p0[i] + 3 * (1 - t) ** 2 * t * p1[i] + 3 * (1 - t) * t ** 2 * p2[i] + t ** 3 * p3[i] for i in (0, 1))
            for t in [j / n for j in range(n + 1)]]


def mark_layer(size: int, u: float, cream, gold) -> Image.Image:
    """The mark centred on a transparent size x size canvas. u = pixels per grid unit."""
    s = size * SS
    k = u * SS
    c = s / 2 - 70 * k                                   # grid point (70, 70) lands on the canvas centre
    w = STROKE * k
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def P(pt):
        return (c + pt[0] * k, c + pt[1] * k)

    def path(points, rgb):
        pts = [P(q) for q in points]
        d.line(pts, fill=rgb + (255,), width=int(w), joint="curve")
        for x, y in (pts[0], pts[-1]):
            d.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill=rgb + (255,))

    path(list(BARS[1]), gold)                                  # the lower bar is gold, like the leg: what has been settled
    path([BOWL[0], BOWL[1]] + _bezier(BOWL[1], BOWL[2], BOWL[3], BOWL[4]), cream)
    path(list(BARS[0]), cream)
    path(list(LEG), gold)
    return img.resize((size, size), Image.LANCZOS)


def mark_layer_mono(size: int, u: float) -> Image.Image:
    """Single-colour version for Android themed icons."""
    return mark_layer(size, u, (255, 255, 255), (255, 255, 255))


def tile(size: int, rounded=True, u_ratio=1.15) -> Image.Image:
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
  <g fill="none" stroke-width="12" stroke-linecap="round" stroke-linejoin="round">
    <path d="M45 30 H67 C94 30 94 74 62 74 M41 30 H97" stroke="#FFF8E7"/>
    <path d="M41 54 H97 M62 74 L94 112" stroke="#F2A900"/>
  </g>
</svg>
"""
SVG_HORIZONTAL = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 560 140" role="img" aria-label="UdhaarSaathi">
  <title>UdhaarSaathi</title>
  <rect width="140" height="140" rx="32" fill="#0B6E4F"/>
  <g fill="none" stroke-width="12" stroke-linecap="round" stroke-linejoin="round">
    <path d="M45 30 H67 C94 30 94 74 62 74 M41 30 H97" stroke="#FFF8E7"/>
    <path d="M41 54 H97 M62 74 L94 112" stroke="#F2A900"/>
  </g>
  <text x="170" y="92" font-family="'Segoe UI','Noto Sans',Arial,sans-serif" font-size="68" font-weight="700"><tspan fill="#0B6E4F">Udhaar</tspan><tspan fill="#C48200">Saathi</tspan></text>
</svg>
"""


def main() -> None:
    # phone app
    save(tile(1024, rounded=False, u_ratio=1.15).convert("RGBA"), "mobile/assets/icon.png")
    save(Image.new("RGBA", (1024, 1024), GREEN + (255,)), "mobile/assets/android-icon-background.png")
    save(mark_layer(1024, 5.0, CREAM, GOLD), "mobile/assets/android-icon-foreground.png")        # inside Android's safe circle
    save(mark_layer_mono(1024, 5.0), "mobile/assets/android-icon-monochrome.png")
    save(mark_layer(1024, 6.2, CREAM, GOLD), "mobile/assets/splash-icon.png")
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
