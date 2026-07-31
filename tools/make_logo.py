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
import random
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


DEEP = (8, 22, 46)
SHALLOW = (40, 100, 146)
SANDC = (150, 126, 84)
SAND_L = (186, 162, 116)
SAND_D = (104, 86, 58)
KELP_DARK = (14, 54, 54)
KELP_MID = (26, 94, 76)
KELP_LIT = (58, 168, 112)
CORAL_PINK = (196, 92, 128)
CORAL_PURPLE = (126, 82, 172)
SHELL = (222, 176, 190)


def scene(w=960, h=720):
    """The full-bleed carousel background.

    This slot is `pos 0 0 / size 1 1` in the theme -- it is stretched over the
    entire screen -- so it is the background for our system rather than a badge
    sitting on top of one. Hence no frame and no panel: the water runs to all
    four edges and the art has to work as a backdrop with the theme's own text
    drawn over it. Authored 4:3 to match the panel it gets stretched onto.
    """
    from PIL import Image

    scr = clawd.Screen(logical=(w, h), plain=True)
    scr.clear()
    sand_y = int(h * 0.74)

    def water_at(y):
        f = min(1.0, max(0.0, y / float(sand_y))) ** 0.85
        return tuple(int(SHALLOW[i] + (DEEP[i] - SHALLOW[i]) * f) for i in range(3))

    for y in range(sand_y):
        scr.rect(0, y, w, 1, water_at(y))

    # light shafts from the surface. They have to be pre-blended against the
    # gradient underneath: the blitter has no alpha, it only copies pixels.
    for sx, sw, lean in ((90, 74, 70), (300, 120, 46), (545, 86, 78), (790, 58, 34)):
        for y in range(sand_y):
            k = y / float(sand_y)
            base = water_at(y)
            fade = (1.0 - k) ** 1.35
            col = tuple(min(255, int(base[j] + (225 - base[j]) * 0.17 * fade))
                        for j in range(3))
            scr.rect(int(sx + lean * k), y, max(2, int(sw * (1 - 0.3 * k))), 1, col)

    def kelp(x0, height, width, col, phase, lean=0.0):
        seg = 15
        y, k = sand_y + 6, 0
        while y > sand_y - height:
            off = int(math.sin(phase + k * 0.42) * (5 + k * 0.55) + lean * k)
            scr.rect(x0 + off, y - seg, max(3, width - k // 4), seg + 1, col)
            y -= seg
            k += 1

    # dark kelp forest hugging both edges, lighter blades in front
    for x0, hh, ww, col, ph, ln in (
            (-6, 640, 46, KELP_DARK, 0.0, 0.6), (46, 560, 34, KELP_DARK, 1.3, 0.4),
            (104, 430, 24, KELP_MID, 2.4, 0.3), (150, 330, 16, KELP_LIT, 0.7, 0.2),
            (w - 44, 620, 46, KELP_DARK, 2.0, -0.6),
            (w - 96, 520, 32, KELP_DARK, 0.4, -0.4),
            (w - 140, 400, 22, KELP_MID, 1.7, -0.3),
            (w - 186, 300, 15, KELP_LIT, 3.0, -0.2)):
        kelp(x0, hh, ww, col, ph, ln)

    def bubble(bx, by, s):
        """A square outline reads as a box, not a bubble. Cutting the corners
        is enough to make it round at this pixel size."""
        c = (120, 190, 220)
        n = max(1, s // 4)                      # corner bite
        t = 2 if s > 8 else 1
        scr.rect(bx + n, by, s - 2 * n, t, c)              # top
        scr.rect(bx + n, by + s - t, s - 2 * n, t, c)      # bottom
        scr.rect(bx, by + n, t, s - 2 * n, c)              # left
        scr.rect(bx + s - t, by + n, t, s - 2 * n, c)      # right
        for dx, dy in ((n - t, n - t), (s - n, n - t),
                       (n - t, s - n), (s - n, s - n)):    # corner pixels
            scr.rect(bx + dx, by + dy, t, t, c)
        if s >= 9:                                          # highlight
            scr.rect(bx + n, by + n, 2, 2, (205, 238, 252))

    # bubbles, denser and larger nearer the surface
    rnd = random.Random(11)
    for _ in range(46):
        by = rnd.randrange(20, sand_y - 20)
        bx = rnd.randrange(10, w - 30)
        s = rnd.choice((5, 7, 9, 12, 16))
        if by > sand_y * 0.6 and s > 9:
            continue
        bubble(bx, by, s)

    # sea floor with an uneven edge, so it doesn't read as a drawn rectangle
    for x in range(w):
        d = int(math.sin(x / 148.0) * 13 + math.sin(x / 43.0) * 5)
        ytop = sand_y + d
        scr.rect(x, ytop, 1, h - ytop, SANDC)
        scr.rect(x, ytop, 1, 5, SAND_L)

    for _ in range(70):                       # pebbles
        px = rnd.randrange(6, w - 12)
        py = rnd.randrange(sand_y + 26, h - 6)
        s = rnd.choice((3, 4, 6))
        scr.rect(px, py, s + 2, s, SAND_D if rnd.random() < 0.6 else (128, 146, 168))

    # coral and shells, low and to the sides so the crab keeps the middle
    for cx, base_col, tip in ((66, CORAL_PURPLE, (170, 130, 214)),
                              (w - 120, CORAL_PINK, (232, 140, 172))):
        for i in range(5):
            bx = cx + i * 15
            bh = 40 + (i % 3) * 26
            scr.rect(bx, sand_y + 24 - bh, 10, bh, base_col)
            scr.rect(bx - 3, sand_y + 24 - bh, 16, 8, tip)
    for sx in (200, w - 230):
        sy = h - 60
        scr.rect(sx, sy, 44, 10, SHELL)
        scr.rect(sx + 5, sy - 8, 34, 10, SHELL)
        scr.rect(sx + 13, sy - 15, 18, 9, (240, 205, 215))

    # the crab, centre stage. `floor` is where his legs land, so it wants to be
    # just below the sand line -- much lower and he's buried to the shoulders.
    sc = 14
    floor = sand_y + 34
    pet = clawd.Clawd(0, floor, sc=sc)
    pet.x = float(w // 2 - 10 * sc)
    pet.blink_until = 0
    pet.next_blink = clawd.time.time() + 9999
    pet.pcur = [0.0, 0.0]
    pet.pupil = (0, 0)
    pet.draw(scr, 0)

    # wordmark, two lines, in the reference's coral-over-cream
    for text, ty, col in (("POCKET", 118, clawd.ACCENT), ("CLAWD", 214, (238, 226, 200))):
        ts = 11
        tx = (w - scr.text_w(text, ts)) // 2
        for dx, dy in ((0, 5), (5, 0), (5, 5)):
            scr.text(tx + dx, ty + dy, text, (18, 34, 56), ts)
        scr.text(tx, ty, text, col, ts)

    return Image.frombytes("RGBA", (w, h), bytes(scr.buf), "raw", "BGRA").convert("RGB")


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

    bg = scene()
    bgp = os.path.join(outdir, "background_icon.png")
    bg.save(bgp)
    print("wrote %s (%dx%d)" % (bgp, bg.width, bg.height))

    for src, name in ((args.out, "system.svg"), (alt, "logo.svg")):
        w, h = svg_wrapper(src, os.path.join(outdir, name))
        print("wrote %s (%dx%d)" % (os.path.join(outdir, name), w, h))
    return 0


if __name__ == "__main__":
    sys.exit(main())
