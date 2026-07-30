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
import math
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


def svg_wrapper(png_path, out_path):
    """Some themes reference logo.svg rather than logo.png. Rather than trace
    the pixel art into vectors, wrap the PNG in a one-element SVG -- valid, and
    it renders identically."""
    import base64
    from PIL import Image

    with open(png_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    w, h = Image.open(png_path).size
    svg = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'xmlns:xlink="http://www.w3.org/1999/xlink" '
        'width="%d" height="%d" viewBox="0 0 %d %d">\n'
        '  <image width="%d" height="%d" image-rendering="pixelated" '
        'xlink:href="data:image/png;base64,%s"/>\n'
        '</svg>\n' % (w, h, w, h, w, h, b64))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(svg)
    return w, h


def background(scale=13):
    """The big watermark some themes show behind the system name.

    Themes ship their own art here -- the ArkOS default puts a Doom cyberdemon
    behind Ports -- so ours has to exist or that shows up next to our crab.

    A bare crab on a transparent background clashed with whatever the theme
    puts behind it, so this draws the actual tank: the dark water gives the
    coral crab something to sit against, it's right-aligned the way these
    slots are used, and it says what the app is at a glance."""
    from PIL import Image

    W, H = 960, 540
    scr = clawd.Screen(logical=(W, H), plain=True)
    scr.clear()

    # --- the tank, right-aligned ---
    tx, ty, tw, th = 470, 60, 440, 420
    clawd.panel(scr, tx, ty, tw, th, "POCKET CLAWD")

    ix, iy = tx + 6, ty + 6
    iw, ih = tw - 12, th - 12
    sand_h = 46
    water_h = ih - sand_h
    band = water_h // 3
    mid = tuple((a + b) // 2 for a, b in zip(clawd.WATER_TOP, clawd.WATER))
    scr.rect(ix, iy, iw, band, clawd.WATER_TOP)
    scr.rect(ix, iy + band, iw, band, mid)
    scr.rect(ix, iy + 2 * band, iw, water_h - 2 * band, clawd.WATER)

    # light shafts from the surface
    for i in range(4):
        rx = ix + 40 + i * (iw // 4) + (i % 2) * 14
        scr.rect(rx, iy, 7, band + 40, (44, 84, 128))

    # sand
    sy = iy + water_h
    scr.rect(ix, sy, iw, sand_h, clawd.SAND)
    scr.rect(ix, sy - 5, iw, 6, clawd.SAND_D)

    # seaweed at the edges only -- anything nearer the middle pokes through
    # the crab, which has no depth sorting to hide behind
    for i, wx in enumerate((ix + 24, ix + iw - 40)):
        segs = 9 + (i % 2) * 3
        for k in range(segs):
            byy = sy - k * 17
            if byy < iy + 30:
                break
            off = int(math.sin(i * 2.1 + k * 0.55) * (3 + k * 0.8))
            col = clawd.WEED if k % 2 else clawd.WEED_D
            if k >= segs - 2:
                col = (72, 200, 120)
            scr.rect(wx + off, byy - 17, 10, 19, col)

    # bubbles
    for i in range(14):
        bx = ix + 24 + (i * 71) % (iw - 48)
        byy = iy + 24 + (i * 137) % (water_h - 40)
        s = 4 + (i % 3) * 3
        scr.frame(bx, byy, s + 3, s + 3, (120, 190, 220), 2)

    # starfish on the sand
    sfx, sfy = ix + 26, sy + 12
    scr.rect(sfx + 6, sfy, 6, 20, clawd.STARFISH)
    scr.rect(sfx, sfy + 7, 20, 6, clawd.STARFISH)

    # A little heads-up display floating in the tank. Without it this is just a
    # crab in a fish tank; the meters are what say "usage monitor".
    hx, hy, hw = ix + 26, iy + 26, iw - 52
    scr.rect(hx, hy, hw, 74, (18, 26, 44))
    scr.frame(hx, hy, hw, 74, clawd.EDGE, 2)
    for row, (label, pct, col) in enumerate((("5H", 0.36, clawd.GOOD),
                                             ("7D", 0.72, clawd.WARN))):
        by = hy + 14 + row * 32
        scr.text(hx + 10, by + 2, label, clawd.DIM, 2)
        bx = hx + 48
        bw = hw - 62
        scr.rect(bx, by, bw, 16, clawd.TRACK)
        scr.rect(bx, by, int(bw * pct), 16, col)
        scr.rect(bx, by, int(bw * pct) - 4, 3,
                 tuple(min(255, c + 45) for c in col))

    # --- the cast ---
    # Clawd is 36 sprite cells wide once both claws are out, so pick the cell
    # size from the tank rather than hardcoding it and having claws hang out
    # through the glass.
    scale = min(scale, max(6, (iw - 56) // 36))
    floor = sy + 12
    pet = clawd.Clawd(0, floor, sc=scale)
    pet.x = float(ix + iw // 2 - 10 * scale)
    pet.blink_until = 0
    pet.next_blink = clawd.time.time() + 9999
    pet.pcur = [0.0, 0.0]
    pet.pupil = (0, 0)

    friends = []
    if clawd.PETS:
        poses = [p for p in ("waving", "happy", "celebrating") if p in clawd.PETS]
        for i, name in enumerate(poses[:2]):
            fx = ix + 62 if i == 0 else ix + iw - 66
            fr = clawd.Friend(name, fx, floor + 4)
            fr.next_hop = clawd.time.time() + 9999
            friends.append(fr)
    for fr in friends:
        fr.draw(scr)
    pet.draw(scr, 0)

    img = Image.frombytes("RGBA", (W, H), bytes(scr.buf), "raw", "BGRA")
    bg = (clawd.BG[0], clawd.BG[1], clawd.BG[2])
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    src, dst = img.load(), out.load()
    for y in range(H):
        for x in range(W):
            r, g, b, _a = src[x, y]
            if (r, g, b) != bg:
                dst[x, y] = (r, g, b, 255)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scale", type=int, default=10)
    ap.add_argument("--out", default=os.path.join(ROOT, "install", "theme", "system.png"))
    ap.add_argument("--no-wordmark", action="store_true")
    args = ap.parse_args()

    outdir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(outdir, exist_ok=True)

    img = render(args.scale, not args.no_wordmark)
    img.save(args.out)
    print("wrote %s (%dx%d)" % (args.out, img.width, img.height))

    if args.no_wordmark:
        return 0

    # a mark with no text, for themes that want a small badge
    mark = render(args.scale, False)
    alt = os.path.join(outdir, "logo.png")
    mark.save(alt)
    print("wrote %s (%dx%d)" % (alt, mark.width, mark.height))

    bg = background()
    bgp = os.path.join(outdir, "background_icon.png")
    bg.save(bgp)
    print("wrote %s (%dx%d)" % (bgp, bg.width, bg.height))

    for src, name in ((args.out, "system.svg"), (alt, "logo.svg")):
        w, h = svg_wrapper(src, os.path.join(outdir, name))
        print("wrote %s (%dx%d)" % (os.path.join(outdir, name), w, h))
    return 0


if __name__ == "__main__":
    sys.exit(main())
