"""App icon, drawn with Pillow (an original design: checklist + tick)."""
from __future__ import annotations

from PIL import Image, ImageDraw


def make_icon(size: int = 512) -> Image.Image:
    s = size
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((s * .04, s * .04, s * .96, s * .96), radius=s * .2,
                        fill=(10, 37, 64, 255))
    # 3x3 grid of cards
    cell = s * .17
    gap = s * .05
    x0 = s * .19
    y0 = s * .19
    for r in range(3):
        for c in range(3):
            x = x0 + c * (cell + gap)
            y = y0 + r * (cell + gap)
            fill = (31, 76, 122, 255) if (r, c) != (2, 2) else (242, 194, 48, 255)
            d.rounded_rectangle((x, y, x + cell, y + cell), radius=s * .035, fill=fill)
    # big golden tick
    w = int(s * .085)
    pts = [(s * .30, s * .52), (s * .45, s * .67), (s * .76, s * .30)]
    d.line(pts, fill=(255, 255, 255, 255), width=w + int(s * .05), joint="curve")
    d.line(pts, fill=(242, 194, 48, 255), width=w, joint="curve")
    return im


if __name__ == "__main__":  # used by the build script
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else "icon.png"
    make_icon(1024).save(out)
    print("icon written to", out)
