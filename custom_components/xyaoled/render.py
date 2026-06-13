"""Pillow-based rendering for the 64x16 panel (text, mono art, full-colour GIFs).

All functions here are synchronous and CPU-bound; call them via an executor.
Vendored from the xyaoled library in this repository.
"""
from __future__ import annotations

import io
import math
import os

from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageSequence

from .protocol import H, W

# Bundled font first: guarantees identical rendering (incl. umlauts and other
# Latin-1 glyphs) on every install. Pillow's embedded fallback font has no
# umlaut glyphs and renders them as boxes.
BUNDLED_FONT = os.path.join(os.path.dirname(__file__), "fonts", "DejaVuSansMono.ttf")

FONT_PATHS = [
    BUNDLED_FONT,
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/System/Library/Fonts/Monaco.ttf",
    "C:\\Windows\\Fonts\\consola.ttf",
]


def _load_font(size: int, font_path: str | None = None):
    for fp in ([font_path] if font_path else []) + FONT_PATHS:
        try:
            return ImageFont.truetype(fp, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=size)  # Pillow >= 10.1
    except TypeError:
        return ImageFont.load_default()


def _to_grid(img: Image.Image) -> list[list[int]]:
    return [[img.getpixel((c, r)) for c in range(W)] for r in range(H)]


def blank_grid() -> list[list[int]]:
    return [[0] * W for _ in range(H)]


def text_pixel_width(text: str, size: int, font_path: str | None = None) -> int:
    font = _load_font(size, font_path)
    d = ImageDraw.Draw(Image.new("1", (8, 8)))
    bbox = d.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def render_centered(text: str, size: int, font_path: str | None = None) -> list[list[int]]:
    img = Image.new("1", (W, H), 0)
    d = ImageDraw.Draw(img)
    font = _load_font(size, font_path)
    bbox = d.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.text(((W - tw) // 2 - bbox[0], (H - th) // 2 - bbox[1]), text, fill=1, font=font)
    return _to_grid(img)


def _render_wide(text: str, size: int, font_path: str | None, pad_left: int = 0) -> Image.Image:
    font = _load_font(size, font_path)
    probe = ImageDraw.Draw(Image.new("1", (8, 8)))
    bbox = probe.textbbox((0, 0), text, font=font)
    img = Image.new("1", (bbox[2] - bbox[0] + pad_left + 2, H), 0)
    d = ImageDraw.Draw(img)
    d.text((pad_left - bbox[0], (H - (bbox[3] - bbox[1])) // 2 - bbox[1]), text, fill=1, font=font)
    return img


def render_pages(text: str, size: int, font_path: str | None = None) -> list[list[list[int]]]:
    """Split a long string into 64px pages at word boundaries (like the app).

    The size is reduced until the widest single word fits, so no page is
    ever clipped and all pages share one consistent font size.
    """
    d = ImageDraw.Draw(Image.new("1", (8, 8)))
    words = text.split() or [text]
    while size > 6:
        font = _load_font(size, font_path)
        if max(d.textbbox((0, 0), w, font=font)[2] for w in words) <= W - 2:
            break
        size -= 1
    font = _load_font(size, font_path)
    width = lambda s: d.textbbox((0, 0), s, font=font)[2]
    pages, cur = [], ""
    for w in text.split(" "):
        cand = (cur + " " + w).strip()
        if cur and width(cand) > W - 2:
            pages.append(cur)
            cur = w
        else:
            cur = cand
    if cur:
        pages.append(cur)
    return [render_centered(p, size, font_path) for p in pages]


def render_strip(text: str, size: int, font_path: str | None = None,
                 lead: int = 2, trail: int = W) -> list[list[list[int]]]:
    """A wide N*64px strip the device scrolls itself (do NOT pre-shift frames)."""
    img = _render_wide(text, size, font_path, pad_left=lead)
    n = max(1, (img.width + trail + W - 1) // W)
    canvas = Image.new("1", (n * W, H), 0)
    canvas.paste(img, (0, 0))
    return [_to_grid(canvas.crop((f * W, 0, f * W + W, H))) for f in range(n)]


# ---------------------------------------------------------------- mono pixel art

def _heart(cx: int, s: float) -> list[list[int]]:
    g = blank_grid()
    for r in range(H):
        for c in range(W):
            x, y = (c - cx) / s, (9 - r) / s
            if (x * x + y * y - 1) ** 3 - x * x * y * y * y <= 0:
                g[r][c] = 1
    return g


def p_border() -> list[list[int]]:
    g = blank_grid()
    for c in range(W):
        g[0][c] = g[H - 1][c] = 1
    for r in range(H):
        g[r][0] = g[r][W - 1] = 1
    return g


def p_checker() -> list[list[int]]:
    return [[(r // 2 + c // 2) % 2 for c in range(W)] for r in range(H)]


def p_diag() -> list[list[int]]:
    return [[1 if (c - r) % 6 == 0 else 0 for c in range(W)] for r in range(H)]


def p_hearts() -> list[list[int]]:
    g = blank_grid()
    for cx in (11, 32, 53):
        h = _heart(cx, 4.0)
        for r in range(H):
            for c in range(W):
                if h[r][c]:
                    g[r][c] = 1
    return g


def p_smiley() -> list[list[int]]:
    g = blank_grid()
    cx, cy, radius = W // 2, H // 2, 7
    for r in range(H):
        for c in range(W):
            if radius - 0.7 <= math.hypot(c - cx, r - cy) <= radius + 0.4:
                g[r][c] = 1
    for ex in (cx - 3, cx + 3):
        g[cy - 2][ex] = 1
    for c in range(cx - 3, cx + 4):
        rr = cy + 2 + (1 if c in (cx - 3, cx + 3) else 0)
        if 0 <= rr < H:
            g[rr][c] = 1
    return g


def p_invaders() -> list[list[int]]:
    art = ["  X     X  ", "   X   X   ", "  XXXXXXX  ", " XX XXX XX ",
           "XXXXXXXXXXX", "X XXXXXXX X", "X X     X X", "   XX XX   "]
    g = blank_grid()
    for bx in (10, 32, 53):
        for ry, line in enumerate(art):
            for cx, ch in enumerate(line):
                r, c = 4 + ry, bx + cx - len(line) // 2
                if ch == "X" and 0 <= r < H and 0 <= c < W:
                    g[r][c] = 1
    return g


PATTERNS = {
    "blank": blank_grid,
    "border": p_border,
    "checker": p_checker,
    "diag": p_diag,
    "heart": lambda: _heart(W // 2, 5.0),
    "hearts": p_hearts,
    "smiley": p_smiley,
    "invaders": p_invaders,
}


def mono_from_image(path: str, threshold: int = 128, invert: bool = False,
                    fit: str = "contain") -> list[list[int]]:
    img = Image.open(path).convert("L")
    if fit == "stretch":
        img = img.resize((W, H))
    else:
        img = ImageOps.contain(img, (W, H))
        canvas = Image.new("L", (W, H), 0)
        canvas.paste(img, ((W - img.width) // 2, (H - img.height) // 2))
        img = canvas
    return [[1 if (img.getpixel((c, r)) >= threshold) ^ invert else 0
             for c in range(W)] for r in range(H)]


# ------------------------------------------------------------- full colour / GIF

def _fit(im: Image.Image, fit: str) -> Image.Image:
    im = im.convert("RGB")
    if fit == "stretch":
        return im.resize((W, H))
    im2 = ImageOps.contain(im, (W, H))
    canvas = Image.new("RGB", (W, H), (0, 0, 0))
    canvas.paste(im2, ((W - im2.width) // 2, (H - im2.height) // 2))
    return canvas


def make_gif(path: str, fit: str = "contain") -> tuple[bytes, int]:
    """Re-encode any image / animated GIF as a 64x16 GIF89a the panel accepts."""
    src = Image.open(path)
    frames = [_fit(f, fit) for f in ImageSequence.Iterator(src)]
    durs = [f.info.get("duration", 100) for f in ImageSequence.Iterator(src)]
    pal = [fr.convert("P", palette=Image.ADAPTIVE, colors=256) for fr in frames]
    buf = io.BytesIO()
    pal[0].save(buf, format="GIF", save_all=True, append_images=pal[1:],
                duration=durs[:len(pal)] or 100, loop=0, version="GIF89a")
    data = bytearray(buf.getvalue())
    data[:6] = b"GIF89a"
    return bytes(data), len(pal)
