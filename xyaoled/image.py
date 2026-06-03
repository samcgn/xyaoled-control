"""Single-colour pixel graphics: an image file or a built-in pattern -> 64x16 (1bpp)."""
import argparse
import asyncio
import math

from PIL import Image, ImageOps

from . import core
from .core import W, H
from .text import build_mono


def p_blank():
    return [[0] * W for _ in range(H)]


def p_border():
    g = p_blank()
    for c in range(W):
        g[0][c] = g[H - 1][c] = 1
    for r in range(H):
        g[r][0] = g[r][W - 1] = 1
    return g


def p_checker():
    return [[(r // 2 + c // 2) % 2 for c in range(W)] for r in range(H)]


def p_diag():
    return [[1 if (c - r) % 6 == 0 else 0 for c in range(W)] for r in range(H)]


def _heart(cx, s):
    g = p_blank()
    for r in range(H):
        for c in range(W):
            x, y = (c - cx) / s, (9 - r) / s
            if (x * x + y * y - 1) ** 3 - x * x * y * y * y <= 0:
                g[r][c] = 1
    return g


def p_heart():
    return _heart(W // 2, 5.0)


def p_hearts():
    g = p_blank()
    for cx in (11, 32, 53):
        h = _heart(cx, 4.0)
        for r in range(H):
            for c in range(W):
                if h[r][c]:
                    g[r][c] = 1
    return g


def p_smiley():
    g = p_blank()
    cx, cy, R = W // 2, H // 2, 7
    for r in range(H):
        for c in range(W):
            if R - 0.7 <= math.hypot(c - cx, r - cy) <= R + 0.4:
                g[r][c] = 1
    for ex in (cx - 3, cx + 3):
        g[cy - 2][ex] = 1
    for c in range(cx - 3, cx + 4):
        rr = cy + 2 + (1 if c in (cx - 3, cx + 3) else 0)
        if 0 <= rr < H:
            g[rr][c] = 1
    return g


def p_invaders():
    art = ["  X     X  ", "   X   X   ", "  XXXXXXX  ", " XX XXX XX ",
           "XXXXXXXXXXX", "X XXXXXXX X", "X X     X X", "   XX XX   "]
    g = p_blank()
    for bx in (10, 32, 53):
        for ry, line in enumerate(art):
            for cx, ch in enumerate(line):
                r, c = 4 + ry, bx + cx - len(line) // 2
                if ch == "X" and 0 <= r < H and 0 <= c < W:
                    g[r][c] = 1
    return g


PATTERNS = {"blank": p_blank, "border": p_border, "checker": p_checker, "diag": p_diag,
            "heart": p_heart, "hearts": p_hearts, "smiley": p_smiley, "invaders": p_invaders}


def from_image(path, threshold, invert, fit):
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


def main(argv=None):
    ap = argparse.ArgumentParser(description="Single-colour pixel graphics on a XYAO-LED panel.")
    ap.add_argument("source", help="image path OR pattern: " + ", ".join(PATTERNS))
    ap.add_argument("--color", default="255,0,0")
    ap.add_argument("--threshold", type=int, default=128)
    ap.add_argument("--invert", action="store_true")
    ap.add_argument("--fit", choices=["contain", "stretch"], default="contain")
    ap.add_argument("--clear", action="store_true")
    ap.add_argument("--address", default=None)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    rgb = [int(x) for x in a.color.split(",")]
    grid = PATTERNS[a.source]() if a.source in PATTERNS else from_image(a.source, a.threshold, a.invert, a.fit)
    for r in range(H):
        print("".join("#" if grid[r][c] else "." for c in range(W)))
    cmds = build_mono([grid], rgb, 2, scroll=False)
    if a.dry_run:
        print("(not sent)")
        return
    asyncio.run(core.send(cmds, clear_first=a.clear, address=a.address))


if __name__ == "__main__":
    main()
