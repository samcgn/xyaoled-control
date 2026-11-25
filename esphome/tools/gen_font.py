#!/usr/bin/env python3
"""Generate esphome/components/xyao_led/xyao_font.h: bitmap fonts for 16-row panels.

Fonts are rendered from TrueType files (default: the DejaVu family, Bitstream Vera /
public-domain licence). Each glyph is stored column-major, 16 rows per column
(bit n = row n), ASCII 32..126.

    python3 esphome/tools/gen_font.py [--fonts-dir /usr/share/fonts/truetype/dejavu]
"""
import argparse
import os

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BUNDLED = os.path.join(ROOT, "custom_components", "xyaoled", "fonts")
OUT = os.path.join(ROOT, "esphome", "components", "xyao_led", "xyao_font.h")
H = 16

# name, file, size, baseline row (pixels from top to the text baseline)
FONTS = [
    ("mono", "DejaVuSansMono.ttf", 12, 12),
    ("sans", "DejaVuSans.ttf", 12, 12),
    ("bold", "DejaVuSans-Bold.ttf", 12, 12),
    ("italic", "DejaVuSans-Oblique.ttf", 12, 12),
    ("narrow", "DejaVuSansCondensed.ttf", 12, 12),
    ("large", "DejaVuSans-Bold.ttf", 16, 15),
    # "tall": narrow letters with hand-drawn 13-row digits (tall_digits.txt) for numbers beside icons
    ("tall", "DejaVuSansCondensed.ttf", 12, 12),
    # "slim": the 8-row small font stretched vertically to ~14 rows (plus the tall digits): narrow but tall
    ("slim", "DejaVuSansCondensed.ttf", 15, 13),
    # 8-row font for two-line messages: glyphs use rows 0..7 (shifted down 8 for line 2)
    ("small", "DejaVuSansMono.ttf", 8, 6),
]


def find(fname, fonts_dir):
    for d in (BUNDLED, fonts_dir, "/usr/share/fonts/truetype/dejavu", "/Library/Fonts"):
        p = os.path.join(d, fname)
        if d and os.path.exists(p):
            return p
    raise SystemExit(f"font {fname} not found; pass --fonts-dir")


def render(path, size, baseline):
    f = ImageFont.truetype(path, size)
    asc, _ = f.getmetrics()
    widths, cols = [], []
    for code in range(32, 127):
        ch = chr(code)
        adv = max(2, int(round(f.getlength(ch))))
        img = Image.new("1", (adv + 4, H), 0)
        ImageDraw.Draw(img).text((0, baseline - asc), ch, fill=1, font=f)
        cc = []
        for x in range(img.width):
            v = 0
            for y in range(H):
                if img.getpixel((x, y)):
                    v |= 1 << y
            cc.append(v)
        # keep the advance width, but don't cut off ink that overhangs (italics)
        while len(cc) > adv and cc[-1] == 0:
            cc.pop()
        if code == 32:
            cc = [0] * max(3, adv // 2)
        widths.append(len(cc))
        cols.append(cc)
    return widths, cols


def render_squeezed(path, size, baseline, squeeze):
    """Render each glyph at `size`, then squeeze it horizontally (box filter + threshold)."""
    f = ImageFont.truetype(path, size)
    asc, _ = f.getmetrics()
    widths, cols = [], []
    for code in range(32, 127):
        ch = chr(code)
        adv = max(2, int(round(f.getlength(ch))))
        img = Image.new("L", (adv, H), 0)
        d = ImageDraw.Draw(img)
        d.fontmode = "1"
        d.text((0, baseline - asc), ch, fill=255, font=f)
        nw = max(2, int(round(adv * squeeze)))
        img = img.resize((nw, H), Image.BOX).point(lambda v: 255 if v >= 110 else 0)
        cc = []
        for x in range(nw):
            v = 0
            for y in range(H):
                if img.getpixel((x, y)):
                    v |= 1 << y
            cc.append(v)
        if code == 32:
            cc = [0] * 3
        widths.append(len(cc))
        cols.append(cc)
    return widths, cols


def parse_glyphs(path, top):
    """Hand-drawn glyphs: a one-character name line, then rows of '.'/'#'. Adds 1 blank column."""
    out, name, rows = [], None, []

    def flush():
        if name is not None and rows:
            w = max(len(r) for r in rows)
            cols = []
            for x in range(w):
                v = 0
                for y, r in enumerate(rows):
                    if x < len(r) and r[x] == "#":
                        v |= 1 << (top + y)
                cols.append(v)
            out.append((name, cols + [0]))

    for line in open(path):
        line = line.rstrip("\n")
        if line.startswith("# "):
            continue
        if not line.strip():
            flush()
            name, rows = None, []
        elif name is None:
            name = line.strip()
        else:
            rows.append(line.strip())
    flush()
    return out


def parse_icons(path):
    """icons.txt: a name line, then rows of '.'/'#' (<=16), blank line between icons.
    Returns [(name, columns)], each icon vertically centred in 16 rows, 1 blank column after."""
    icons, name, rows, colours = [], None, [], (0, 0)
    NAMED = {"red": 0xFF0000, "green": 0x00FF00, "blue": 0x0040FF, "yellow": 0xFFC800, "white": 0xFFFFFF,
             "cyan": 0x00FFFF, "magenta": 0xFF00FF, "orange": 0xFF6400}

    def flush():
        if name and rows:
            w = max(len(r) for r in rows)
            top = (H - len(rows)) // 2
            cols = []
            for x in range(w):
                v = 0
                for y, r in enumerate(rows):
                    if x < len(r) and r[x] == "#":
                        v |= 1 << (top + y)
                cols.append(v)
            icons.append((name, cols + [0], colours))

    for line in open(path):
        line = line.rstrip("\n")
        if line.startswith("#") and not set(line) <= set("#."):
            continue
        if not line.strip():
            flush()
            name, rows, colours = None, [], (0, 0)
        elif name is None:
            parts = line.split()
            name = parts[0]
            if len(parts) >= 3:
                colours = (NAMED[parts[1]], NAMED[parts[2]])
        else:
            rows.append(line.strip())
    flush()
    return icons


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fonts-dir", default="")
    ap.add_argument("--preview", default="Hi 71%")
    a = ap.parse_args()
    out = [
        "#pragma once",
        "#include <cstdint>",
        "// Generated by esphome/tools/gen_font.py from the DejaVu fonts. Do not edit.",
        "// ASCII 32..126, 16 rows, column-major (bit n = row n).",
        "struct XyaoFont {",
        "  const char *name;",
        "  const uint8_t *widths;",
        "  const uint16_t *offsets;",
        "  const uint16_t *columns;",
        "};",
    ]
    table = []
    for name, fname, size, base in FONTS:
        widths, cols = render(find(fname, a.fonts_dir), size, base)
        if name == "slim":
            widths, cols = render_squeezed(find(fname, a.fonts_dir), size, base, 0.7)
        if name == "small":
            for ch, gcols in parse_glyphs(os.path.join(os.path.dirname(os.path.abspath(__file__)), "small_fixes.txt"), top=0):
                widths[ord(ch) - 32] = len(gcols) + 1
                cols[ord(ch) - 32] = [0] + gcols  # keep the font's leading-gap style
            # proportional: trim each glyph to its ink, then one blank column in front (space stays 3 wide)
            for i in range(95):
                c = cols[i]
                if i == 0:
                    cols[i] = [0, 0, 0]
                else:
                    while c and c[0] == 0:
                        c = c[1:]
                    while c and c[-1] == 0:
                        c = c[:-1]
                    cols[i] = [0] + (c or [0])
                widths[i] = len(cols[i])
        if name in ("tall", "slim"):
            for ch, gcols in parse_glyphs(os.path.join(os.path.dirname(os.path.abspath(__file__)), "tall_digits.txt"), top=1):
                widths[ord(ch) - 32] = len(gcols)
                cols[ord(ch) - 32] = gcols
        offs, o = [], 0
        for c in cols:
            offs.append(o)
            o += len(c)
        out.append(f"static const uint8_t XYAO_{name.upper()}_W[95] = {{" + ",".join(map(str, widths)) + "};")
        out.append(f"static const uint16_t XYAO_{name.upper()}_OFF[95] = {{" + ",".join(map(str, offs)) + "};")
        out.append(f"static const uint16_t XYAO_{name.upper()}_COLS[{o}] = {{" +
                   ",".join("0x%04X" % v for c in cols for v in c) + "};")
        table.append(f'  {{"{name}", XYAO_{name.upper()}_W, XYAO_{name.upper()}_OFF, XYAO_{name.upper()}_COLS}},')
        rows = [""] * H
        for ch in a.preview:
            for v in cols[ord(ch) - 32]:
                for y in range(H):
                    rows[y] += "#" if v >> y & 1 else "."
            for y in range(H):
                rows[y] += " "
        print(f"--- {name} ({fname} {size}px, {o} columns)")
        print("\n".join(rows))
    # icons
    icons = parse_icons(os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons.txt"))
    ioff, o2, allcols, names = [], 0, [], []
    for name, cols, _ in icons:
        names.append(name)
        ioff.append(o2)
        allcols += cols
        o2 += len(cols)
    out.append("// top / bottom: fixed 0xRRGGBB colour for rows 0-7 / 8-15, or 0 = use the text colour")
    out.append("struct XyaoIcon {\n  const char *name;\n  uint16_t offset;\n  uint8_t width;\n  uint32_t top, bottom;\n};")
    out.append(f"static const uint16_t XYAO_ICON_COLS[{max(1, o2)}] = {{" + ",".join("0x%04X" % v for v in allcols) + "};")
    out.append(f"static const int XYAO_ICON_COUNT = {len(icons)};")
    out.append("static const XyaoIcon XYAO_ICONS[] = {")
    for (name, cols, (top, bot)), off in zip(icons, ioff):
        out.append(f'  {{"{name}", {off}, {len(cols)}, 0x{top:06X}, 0x{bot:06X}}},')
    out.append("};")
    print("icons:", ", ".join(names))
    out.append(f"static const int XYAO_FONT_COUNT = {len(FONTS)};")
    out.append("static const XyaoFont XYAO_FONTS[] = {")
    out += table
    out.append("};")
    with open(OUT, "w") as fh:
        fh.write("\n".join(out) + "\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
