"""
Generates calm, architectural placeholder photos for demo listings with Pillow.
No network access and no third-party image licensing involved.
"""

import random
from io import BytesIO

from PIL import Image, ImageDraw, ImageFilter

W, H = 1200, 900

# (sky top, sky bottom, ground, building, accent) per palette
PALETTES = [
    ((232, 214, 190), (246, 236, 220), (196, 176, 146), (240, 232, 218), (164, 73, 42)),
    ((196, 214, 222), (236, 240, 236), (178, 170, 140), (250, 246, 238), (30, 58, 47)),
    ((240, 196, 160), (250, 226, 200), (160, 132, 100), (236, 222, 200), (120, 60, 40)),
    ((206, 220, 206), (240, 242, 230), (150, 160, 120), (248, 244, 236), (184, 145, 63)),
    ((60, 70, 96), (214, 160, 130), (70, 66, 58), (220, 206, 186), (240, 190, 110)),  # dusk
    ((222, 206, 214), (244, 236, 232), (170, 150, 140), (246, 240, 236), (92, 74, 110)),
]


def _gradient(top, bottom):
    img = Image.new("RGB", (W, H), top)
    draw = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        draw.line([(0, y), (W, y)], fill=tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return img


def _windows(draw, x0, y0, x1, y1, cols, rows, color, rnd, lit_color=None):
    cw, rh = (x1 - x0) / cols, (y1 - y0) / rows
    for c in range(cols):
        for r in range(rows):
            wx, wy = x0 + c * cw + cw * 0.22, y0 + r * rh + rh * 0.2
            fill = lit_color if lit_color and rnd.random() < 0.35 else color
            draw.rectangle([wx, wy, wx + cw * 0.56, wy + rh * 0.55], fill=fill)


def exterior(kind, palette, seed):
    rnd = random.Random(seed)
    sky_top, sky_bottom, ground, building, accent = palette
    dusk = palette is PALETTES[4]
    img = _gradient(sky_top, sky_bottom)
    d = ImageDraw.Draw(img)
    horizon = int(H * 0.72)
    # distant hills
    for i in range(3):
        shade = tuple(max(0, c - 18 - i * 10) for c in sky_bottom)
        pts = [(0, horizon)]
        for x in range(0, W + 100, 100):
            pts.append((x, horizon - 60 - i * 25 - rnd.randint(0, 50)))
        pts.append((W, horizon))
        d.polygon(pts, fill=shade)
    d.rectangle([0, horizon, W, H], fill=ground)
    win = tuple(max(0, c - 70) for c in building)
    lit = (255, 214, 150) if dusk else None
    if kind == "apartment":
        for bx, bw, bh in ((140, 260, 470), (430, 330, 560), (790, 250, 420)):
            top = horizon - bh
            d.rectangle([bx, top, bx + bw, horizon], fill=building)
            d.rectangle([bx, top, bx + bw, top + 14], fill=accent)
            _windows(d, bx + 14, top + 30, bx + bw - 14, horizon - 20, 4, max(4, bh // 70), win, rnd, lit)
    elif kind == "villa":
        x0, x1, top = 220, 980, horizon - 250
        d.rectangle([x0, top, x1, horizon], fill=building)
        d.rectangle([x0 - 30, top - 26, x1 + 30, top], fill=accent)
        d.rectangle([x0 + 60, top + 60, x0 + 360, horizon - 40], fill=win if not dusk else lit)
        d.rectangle([x0 + 430, top + 60, x1 - 60, top + 150], fill=win)
        d.rectangle([x0 + 520, horizon - 110, x0 + 600, horizon], fill=accent)
        # pool
        d.rectangle([60, horizon + 50, 700, horizon + 110], fill=(120, 180, 196))
        # palms
        for px in (1040, 1110):
            d.line([(px, horizon), (px - 20, horizon - 280)], fill=(90, 70, 50), width=10)
            for a in range(-3, 4):
                d.line([(px - 20, horizon - 280), (px - 20 + a * 45, horizon - 240 + abs(a) * 12)], fill=(60, 100, 70), width=8)
    else:  # townhouse
        n = 4
        unit = 210
        x = 180
        for i in range(n):
            top = horizon - 330 + (i % 2) * 20
            body = tuple(max(0, c - (i % 2) * 12) for c in building)
            d.rectangle([x, top, x + unit, horizon], fill=body)
            d.polygon([(x - 6, top), (x + unit / 2, top - 70), (x + unit + 6, top)], fill=accent)
            _windows(d, x + 20, top + 30, x + unit - 20, horizon - 90, 2, 3, win, rnd, lit)
            d.rectangle([x + unit / 2 - 25, horizon - 80, x + unit / 2 + 25, horizon], fill=tuple(max(0, c - 40) for c in accent))
            x += unit + 6
    return img.filter(ImageFilter.GaussianBlur(0.6))


def interior(palette, seed):
    rnd = random.Random(seed)
    _, sky_bottom, ground, building, accent = palette
    img = Image.new("RGB", (W, H), building)
    d = ImageDraw.Draw(img)
    floor_y = int(H * 0.7)
    d.rectangle([0, floor_y, W, H], fill=tuple(min(255, c + 10) for c in ground))
    for x in range(0, W, 90):
        d.line([(x, floor_y), (x - 160, H)], fill=tuple(max(0, c - 14) for c in ground), width=2)
    # window
    wx0, wx1 = 640, 1080
    d.rectangle([wx0, 140, wx1, floor_y - 40], fill=sky_bottom)
    d.rectangle([wx0, 140, wx1, floor_y - 40], outline=(60, 56, 50), width=10)
    d.line([((wx0 + wx1) / 2, 140), ((wx0 + wx1) / 2, floor_y - 40)], fill=(60, 56, 50), width=8)
    # sofa
    d.rounded_rectangle([110, floor_y - 150, 560, floor_y + 20], 26, fill=accent)
    d.rounded_rectangle([140, floor_y - 210, 530, floor_y - 120], 22, fill=tuple(min(255, c + 25) for c in accent))
    # lamp and rug
    d.line([(600, floor_y + 10), (600, floor_y - 300)], fill=(50, 46, 40), width=6)
    d.ellipse([560, floor_y - 340, 640, floor_y - 280], fill=(240, 220, 180))
    d.ellipse([180, floor_y + 60, 900, floor_y + 180], fill=tuple(max(0, c - 30) for c in building))
    # art
    d.rectangle([180, 170, 360, 330], fill=tuple(rnd.randint(120, 200) for _ in range(3)))
    return img.filter(ImageFilter.GaussianBlur(0.5))


def to_jpeg_bytes(img, quality=82):
    buf = BytesIO()
    img.save(buf, "JPEG", quality=quality, optimize=True, progressive=True)
    return buf.getvalue()
