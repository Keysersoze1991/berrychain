"""Render the BerryChain mark into Android launcher icons with Pillow alone:
legacy ic_launcher.png at every density (gold mark on a navy rounded tile)
and an adaptive icon (gold foreground on a navy background colour).

    python app/tool/make_icons.py
"""

import os

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(ROOT, "android", "app", "src", "main", "res")
NAVY = (12, 31, 51, 255)
GOLD = (217, 166, 43, 255)


def cubic(p0, p1, p2, p3, n=200):
    pts = []
    for i in range(n + 1):
        t = i / n
        u = 1 - t
        x = u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0]
        y = u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1]
        pts.append((x, y))
    return pts


def line(p0, p1, n=200):
    return [(p0[0] + (p1[0] - p0[0]) * i / n, p0[1] + (p1[1] - p0[1]) * i / n) for i in range(n + 1)]


def mark(size, colour, box):
    """Draw the mark (viewBox 0 0 64 80) scaled into `box` = (x, y, w, h) of an RGBA image."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    bx, by, bw, bh = box
    s = min(bw / 64, bh / 80)
    ox, oy = bx + (bw - 64 * s) / 2, by + (bh - 80 * s) / 2
    tr = lambda p: (ox + p[0] * s, oy + p[1] * s)
    r = 4.5 * s                                                    # stroke width 9, round caps

    def stroke(pts):
        for x, y in map(tr, pts):
            d.ellipse((x - r, y - r, x + r, y + r), fill=colour)

    stroke(line((16, 14), (16, 70)))                               # stem
    stroke(line((16, 41), (33, 41)))                               # bowl top
    stroke(cubic((33, 41), (44, 41), (51, 47), (51, 55.5)))        # bowl: h17 c11 0 18 6 18 14.5
    stroke(cubic((51, 55.5), (51, 64), (44, 70), (33, 70)))        #       S44 70 33 70 (reflected control)
    stroke(line((33, 70), (16, 70)))
    stroke(line((5, 41), (16, 41)))                                # crossbar
    cx, cy = tr((33, 25))
    rr = 13.5 * s
    d.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=colour)   # berry
    leaf = cubic((38, 12), (42, 5), (50, 4), (55, 5)) + cubic((55, 5), (54, 11), (49, 17), (41, 16)) + cubic((41, 16), (38, 16), (37, 14), (38, 12))
    d.polygon([tr(p) for p in leaf], fill=colour)
    return img


def tile(size):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, size - 1, size - 1), radius=int(size * 0.22), fill=NAVY)
    m = mark(size, GOLD, (size * 0.22, size * 0.14, size * 0.56, size * 0.72))
    return Image.alpha_composite(img, m)


def foreground(size):
    # adaptive icons: the safe zone is the middle 66/108, so keep the mark inside ~52%
    return mark(size, GOLD, (size * 0.26, size * 0.22, size * 0.48, size * 0.56))


def main():
    big = tile(1024)
    fg = foreground(1024)
    dens = {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}
    for name, px in dens.items():
        folder = os.path.join(RES, f"mipmap-{name}")
        os.makedirs(folder, exist_ok=True)
        big.resize((px, px), Image.LANCZOS).save(os.path.join(folder, "ic_launcher.png"))
        fg.resize((px * 108 // 48, px * 108 // 48), Image.LANCZOS).save(os.path.join(folder, "ic_launcher_foreground.png"))
    any26 = os.path.join(RES, "mipmap-anydpi-v26")
    os.makedirs(any26, exist_ok=True)
    with open(os.path.join(any26, "ic_launcher.xml"), "w", encoding="utf-8", newline="\n") as f:
        f.write('<?xml version="1.0" encoding="utf-8"?>\n<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">\n'
                '    <background android:drawable="@color/ic_launcher_background"/>\n'
                '    <foreground android:drawable="@mipmap/ic_launcher_foreground"/>\n</adaptive-icon>\n')
    values = os.path.join(RES, "values")
    os.makedirs(values, exist_ok=True)
    with open(os.path.join(values, "ic_launcher_background.xml"), "w", encoding="utf-8", newline="\n") as f:
        f.write('<?xml version="1.0" encoding="utf-8"?>\n<resources>\n    <color name="ic_launcher_background">#0C1F33</color>\n</resources>\n')
    big.save(os.path.join(ROOT, "tool", "icon-preview.png"))
    print("icons written; preview at app/tool/icon-preview.png")


if __name__ == "__main__":
    main()
