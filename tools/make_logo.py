#!/usr/bin/env python3
"""Draw the carousel logo.

EmulationStation shows one image per system on the main carousel. Rather than
draw a separate mascot in an image editor, this renders the real Clawd with the
real widget code at a bigger sprite size, then keys the background out to
transparency -- so the icon on the carousel is exactly the crab in the app.

    python tools/make_logo.py                 # install/theme/system.png
    python tools/make_logo.py --scale 12      # chunkier

Needs Pillow, on the PC only. The console never runs this.
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "device"))
os.environ.setdefault("CLAWD_SIM", "1")

import clawd  # noqa: E402


def render(scale, wordmark=True):
    from PIL import Image

    body_w = len(clawd.BODY[0]) * scale          # crab body
    claw_w = len(clawd.CLAW_L[0]) * scale
    pad = scale * 2
    w = body_w + 2 * claw_w + 4 * scale + 2 * pad
    crab_h = len(clawd.BODY) * scale + 4 * scale
    text_scale = max(2, scale // 2)
    text = "POCKET CLAWD"
    text_h = (8 * text_scale + 10) if wordmark else 0
    h = crab_h + text_h + 2 * pad

    scr = clawd.Screen(logical=(w, h), plain=True)
    scr.clear()

    crab_x = pad + claw_w + 2 * scale
    floor = pad + crab_h
    pet = clawd.Clawd(crab_x, floor, sc=scale)
    pet.blink_until = 0
    pet.next_blink = clawd.time.time() + 9999
    pet.pcur = [0.0, 0.0]
    pet.pupil = (0, 0)
    pet.draw(scr, 0)

    if wordmark:
        tw = scr.text_w(text, text_scale)
        tx = (w - tw) // 2
        ty = pad + crab_h + 4
        for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
            scr.text(tx + dx, ty + dy, text, clawd.HALO, text_scale)
        scr.text(tx, ty, text, clawd.ACCENT, text_scale)

    img = Image.frombytes("RGBA", (w, h), bytes(scr.buf), "raw", "BGRA")
    # the plain background is a single flat colour, so keying it out is exact
    bg = (clawd.BG[0], clawd.BG[1], clawd.BG[2])
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    src = img.load()
    dst = out.load()
    for y in range(h):
        for x in range(w):
            r, g, b, _a = src[x, y]
            if (r, g, b) != bg:
                dst[x, y] = (r, g, b, 255)
    return out.crop(out.getbbox() or (0, 0, w, h))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scale", type=int, default=10)
    ap.add_argument("--out", default=os.path.join(ROOT, "install", "theme", "system.png"))
    ap.add_argument("--no-wordmark", action="store_true")
    args = ap.parse_args()

    img = render(args.scale, not args.no_wordmark)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    img.save(args.out)
    print("wrote %s (%dx%d)" % (args.out, img.width, img.height))

    # a square-ish mark with no text, for themes that want a small badge
    if not args.no_wordmark:
        mark = render(args.scale, False)
        alt = os.path.join(os.path.dirname(os.path.abspath(args.out)), "logo.png")
        mark.save(alt)
        print("wrote %s (%dx%d)" % (alt, mark.width, mark.height))
    return 0


if __name__ == "__main__":
    sys.exit(main())
