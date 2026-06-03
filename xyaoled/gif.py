"""Full-colour images and animations via an embedded GIF89a (mode 0x08)."""
import argparse
import asyncio
import io

from PIL import Image, ImageSequence, ImageOps

from . import core
from .core import W, H, frame

# 11 fixed header bytes (after the 2-byte sub-length) for a STATIC full-colour GIF.
STATIC_HDR_TAIL = bytes([0x00, 0x02, 0x00, 0x01, 0x01, 0x00, 0x00, 0x01, 0x00, 0x08, 0x00])

# Max GIF bytes carried in a single 0x0207 frame (frame len cap 10000 - 11 - 13).
MAX_0207_GIF = 10000 - 11 - 13


def _fit(im, fit):
    im = im.convert("RGB")
    if fit == "stretch":
        return im.resize((W, H))
    im2 = ImageOps.contain(im, (W, H))
    canvas = Image.new("RGB", (W, H), (0, 0, 0))
    canvas.paste(im2, ((W - im2.width) // 2, (H - im2.height) // 2))
    return canvas


def make_gif(path, fit):
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


def build_cmds(gif, nframes, seq):
    """Static colour image (single 0x0207) or animation (always 0x0207 + 0x0209)."""
    color = frame(0x0204, seq, bytes([0xFF, 0x00]))
    if nframes <= 1:
        payload = len(gif).to_bytes(2, "little") + STATIC_HDR_TAIL + gif
        return [color, frame(0x0207, seq, payload)]
    # Animation: header byte 3 = 0x03, byte 11 = 0x03, frame count at byte 9.
    # Bytes 5..8 are don't-care. Animations MUST be split into 0x0207 + 0x0209.
    hdr = bytes([0x00, 0x03, 0x00, 0x00, 0x00, 0x00, 0x00, nframes & 0xFF, 0x00, 0x03, 0x00])
    split = MAX_0207_GIF if len(gif) > MAX_0207_GIF else max(1, len(gif) // 2)
    p1, p2 = gif[:split], gif[split:]
    pl207 = len(gif).to_bytes(2, "little") + hdr + p1
    pl209 = len(p2).to_bytes(2, "little") + bytes([0x00, 0x02, 0x00]) + p2
    return [color, frame(0x0207, seq, pl207), frame(0x0209, seq, pl209)]


def main(argv=None):
    ap = argparse.ArgumentParser(description="Full-colour image / animation on a XYAO-LED panel.")
    ap.add_argument("image", help="any image, or an animated GIF for animation")
    ap.add_argument("--fit", choices=["contain", "stretch"], default="contain")
    ap.add_argument("--clear", action="store_true")
    ap.add_argument("--address", default=None)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    gif, n = make_gif(a.image, a.fit)
    cmds = build_cmds(gif, n, 2)
    print(f"{n} frame(s), GIF {len(gif)} bytes, {len(cmds)} commands")
    if a.dry_run:
        print("(not sent)")
        return
    asyncio.run(core.send(cmds, clear_first=a.clear, address=a.address,
                          on_notify=lambda _, d: print("notify:", bytes(d).hex(" "))))


if __name__ == "__main__":
    main()
