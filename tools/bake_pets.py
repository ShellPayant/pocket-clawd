#!/usr/bin/env python3
"""Turn the clawd-pet SVGs into framebuffer sprites.

The console has no SVG renderer and no compositor -- it copies rows of raw BGRA
bytes into memory. So each pet is pre-rendered here into `device/pets/`.

The upstream SVGs animate using CSS keyframes, which is why they move on
GitHub. To capture that, each one is rendered in headless Chrome eight times
with the animation paused at eight points through its cycle. Chrome won't give
us a transparent screenshot, so every frame is rendered twice on two different
background colours: the pixels that come out identical are the opaque ones, and
the rest are background. That's an exact alpha mask with no fringing, which
matters because the blitter has no blending -- a pixel is either drawn or not.

    python tools/bake_pets.py                    # all of assets/pets-svg
    python tools/bake_pets.py --only happy 429
    python tools/bake_pets.py --height 72

Adding more pets: grab any SVG from https://github.com/abderrahimghazali/clawd-pet
into assets/pets-svg/ as `clawd-<name>.svg`, re-run this, and it appears in the
tank. Needs Chrome (or Edge) and Pillow, on the PC only.

Two things to know before you re-bake a pet that already exists:

* Existing sprites are never overwritten without `--force`. The ones in the
  repo were tuned by hand and this will not reproduce them exactly.
* Freezing the animation applies one offset to every element, which flattens
  any stagger the artist built in -- so decorative bits that twinkle in
  sequence (the sparkles around `happy`, for instance) can come out missing.
  For a new pet that usually doesn't matter. If it does, bake at a few
  different `--height` values and pick the one that reads best on the panel.

Output format, per frame: uint16 width, uint16 height, then width*height BGRA
pixels, alpha 0 or 255. Named `<pet>_f<k>.raw`.
"""
import argparse
import glob
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SVG_DIR = os.path.join(ROOT, "assets", "pets-svg")
OUT_DIR = os.path.join(ROOT, "device", "pets")

FRAMES = 8          # samples through the animation cycle
CYCLE = 1.0         # seconds; the upstream animations are 1s loops
CELL = 200          # render size per frame, before downscaling
BG_A = (255, 0, 255)
BG_B = (0, 255, 0)

CHROME_CANDIDATES = [
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
    "microsoft-edge", "chrome",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


def find_chrome():
    for c in CHROME_CANDIDATES:
        if os.path.sep in c or (os.name == "nt" and ":" in c):
            if os.path.exists(c):
                return c
        else:
            found = shutil.which(c)
            if found:
                return found
    return None


def build_page(svg_text, bg):
    """One row of FRAMES cells, each the same SVG frozen at a different point
    in its animation."""
    # strip the outer width/height so our CSS controls the size
    svg_text = re.sub(r'\s(width|height)="[^"]*"', "", svg_text, count=2)
    cells = []
    for k in range(FRAMES):
        delay = -(CYCLE * k / FRAMES)
        cells.append(
            '<div class="cell"><style scoped></style>'
            '<div class="pin" style="--d:%fs">%s</div></div>' % (delay, svg_text))
    return """<!doctype html><html><head><meta charset="utf-8"><style>
      html,body{margin:0;padding:0;background:rgb(%d,%d,%d);}
      .row{display:flex;}
      .cell{width:%dpx;height:%dpx;overflow:hidden;}
      .pin svg{width:%dpx;height:%dpx;display:block;}
      /* freeze every animation at this cell's offset */
      .pin *{animation-play-state:paused !important;
             animation-delay:var(--d) !important;}
    </style></head><body><div class="row">%s</div></body></html>
    """ % (bg[0], bg[1], bg[2], CELL, CELL, CELL, CELL, "".join(cells))


def shoot(chrome, html, png, width, height):
    cmd = [chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars",
           "--force-device-scale-factor=1",
           "--virtual-time-budget=2000",
           "--screenshot=%s" % png,
           "--window-size=%d,%d" % (width, height),
           "file:///%s" % html.replace("\\", "/")]
    r = subprocess.run(cmd, capture_output=True)
    if not os.path.exists(png):
        raise RuntimeError("Chrome produced no screenshot: %s"
                           % r.stderr.decode("utf-8", "replace")[-400:])


def bake(chrome, svg_path, out_dir, target_h, workdir, force=False):
    from PIL import Image

    name = os.path.splitext(os.path.basename(svg_path))[0]
    if name.startswith("clawd-"):
        name = name[len("clawd-"):]
    if not force and os.path.exists(os.path.join(out_dir, "%s_f0.raw" % name)):
        return name, 0, (0, 0)
    with open(svg_path, encoding="utf-8") as f:
        svg = f.read()

    shots = []
    for idx, bg in enumerate((BG_A, BG_B)):
        html = os.path.join(workdir, "%s_%d.html" % (name, idx))
        with open(html, "w", encoding="utf-8") as f:
            f.write(build_page(svg, bg))
        png = os.path.join(workdir, "%s_%d.png" % (name, idx))
        shoot(chrome, html, png, CELL * FRAMES, CELL)
        shots.append(Image.open(png).convert("RGB"))

    a, b = shots
    if a.size != b.size:
        raise RuntimeError("%s: renders disagree on size" % name)

    # opaque exactly where the two backgrounds made no difference
    frames = []
    for k in range(FRAMES):
        box = (k * CELL, 0, (k + 1) * CELL, CELL)
        ca, cb = a.crop(box), b.crop(box)
        rgba = Image.new("RGBA", (CELL, CELL), (0, 0, 0, 0))
        pa, pb, pd = ca.load(), cb.load(), rgba.load()
        for y in range(CELL):
            for x in range(CELL):
                if pa[x, y] == pb[x, y]:
                    r, g, bl = pa[x, y]
                    pd[x, y] = (r, g, bl, 255)
        frames.append(rgba)

    # one bounding box for every frame, so the sprite doesn't jitter
    box = None
    for fr in frames:
        bb = fr.getbbox()
        if bb is None:
            continue
        box = bb if box is None else (min(box[0], bb[0]), min(box[1], bb[1]),
                                      max(box[2], bb[2]), max(box[3], bb[3]))
    if box is None:
        raise RuntimeError("%s: rendered empty" % name)

    written = 0
    for k, fr in enumerate(frames):
        fr = fr.crop(box)
        scale = target_h / float(fr.height)
        size = (max(1, int(round(fr.width * scale))), target_h)
        # LANCZOS keeps thin shapes alive at this size; the alpha it produces is
        # soft, so snap it back to on/off for the blitter
        fr = fr.resize(size, Image.LANCZOS)
        px = fr.load()
        out = bytearray()
        out += struct.pack("<HH", fr.width, fr.height)
        for y in range(fr.height):
            for x in range(fr.width):
                r, g, b, al = px[x, y]
                if al >= 128:
                    out += struct.pack("<BBBB", b, g, r, 255)
                else:
                    out += b"\x00\x00\x00\x00"
        with open(os.path.join(out_dir, "%s_f%d.raw" % (name, k)), "wb") as f:
            f.write(bytes(out))
        written += 1
    return name, written, (box[2] - box[0], box[3] - box[1])


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="*", help="just these pets, by short name")
    ap.add_argument("--height", type=int, default=64,
                    help="sprite height in pixels (default 64)")
    ap.add_argument("--svg-dir", default=SVG_DIR)
    ap.add_argument("--out", default=OUT_DIR)
    ap.add_argument("--force", action="store_true",
                    help="re-bake pets that already have sprites")
    ap.add_argument("--list", action="store_true",
                    help="show the sprite sizes already installed and exit")
    args = ap.parse_args()

    if args.list:
        seen = {}
        for raw in sorted(glob.glob(os.path.join(args.out, "*_f0.raw"))):
            with open(raw, "rb") as f:
                w, h = struct.unpack("<HH", f.read(4))
            seen[os.path.basename(raw)[:-len("_f0.raw")]] = (w, h)
        for name in sorted(seen):
            print("  %-18s %dx%d" % (name, seen[name][0], seen[name][1]))
        print("%d pets installed" % len(seen))
        return 0

    chrome = find_chrome()
    if not chrome:
        print("Chrome or Edge not found -- needed to render the animated SVGs.")
        print("The pre-baked sprites in device/pets/ are already committed, so")
        print("you only need this if you're adding or changing pets.")
        return 1
    print("using %s" % chrome)

    svgs = sorted(glob.glob(os.path.join(args.svg_dir, "*.svg")))
    if args.only:
        want = set(args.only)
        svgs = [s for s in svgs
                if os.path.basename(s).replace("clawd-", "").replace(".svg", "") in want]
    if not svgs:
        print("no SVGs matched")
        return 1

    os.makedirs(args.out, exist_ok=True)
    workdir = tempfile.mkdtemp(prefix="bake-pets-")
    failed = 0
    try:
        for svg in svgs:
            try:
                name, n, src = bake(chrome, svg, args.out, args.height, workdir,
                                    args.force)
                if n == 0:
                    print("  %-18s already installed (--force to re-bake)" % name)
                else:
                    print("  %-18s %d frames  (source %dx%d)"
                          % (name, n, src[0], src[1]))
            except (RuntimeError, OSError) as exc:
                print("  %-18s FAILED: %s" % (os.path.basename(svg), exc))
                failed += 1
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    print("done%s" % (" (%d failed)" % failed if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
