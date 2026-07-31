#!/usr/bin/env python3
"""Build the promotional artwork: the social preview card and the explanatory
diagrams the README leans on.

    python tools/bake_promo.py                    # everything, into docs/img/
    python tools/bake_promo.py --only social

The visual language follows Anthropic's, because that is what this thing is a
companion for. The rules that matter, taken from their live stylesheet rather
than from the colour-aggregator sites (which disagree with each other and with
reality -- the widely-quoted #CC785C appears nowhere in their assets):

  * warm ivory paper, never pure white; cards sit LIGHTER than the canvas
  * depth comes from surface tone steps and 1px hairlines -- NO drop shadows
  * edges are cut and clean, not torn; think specimen plate, not ripped paper
  * clay #D97757 appears on exactly one element per image, never as decoration
  * body copy is set in serif, not sans -- Georgia is their own declared fallback

Needs Pillow. PC only; the console never runs this.
"""
import argparse
import glob
import os
import random
import struct
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG = os.path.join(ROOT, "docs", "img")
SHOTS = os.path.join(ROOT, "docs", "screenshots")
PETS = os.path.join(ROOT, "device", "pets")

# --- the palette, from anthropic.com's own --swatch-- tokens ---------------
PAPER = (240, 238, 230)      # ivory-medium  #F0EEE6   the canvas
CARD = (250, 249, 245)       # ivory-light   #FAF9F5   raised surface
OAT = (227, 218, 204)        # oat           #E3DACC
MANILLA = (235, 219, 188)    # manilla       #EBDBBC
KRAFT = (212, 162, 127)      # kraft         #D4A27F
INK = (20, 20, 19)           # slate-dark    #141413
INK2 = (61, 61, 58)          # slate-medium  #3D3D3A
MUTED = (176, 174, 165)      # cloud-medium  #B0AEA5
HAIR = (204, 203, 200)       # hairline      #CCCBC8
CLAY = (217, 119, 87)        # clay          #D97757  -- one element only

WIN = r"C:\Windows\Fonts"
SERIF = os.path.join(WIN, "georgia.ttf")
SERIF_B = os.path.join(WIN, "georgiab.ttf")
SERIF_I = os.path.join(WIN, "georgiai.ttf")
SANS = os.path.join(WIN, "seguisb.ttf")
SANS_R = os.path.join(WIN, "segoeui.ttf")


def font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def paper(w, h, tone=PAPER, grain=True):
    """The canvas. A faint stipple stands in for the engraved-plate texture in
    their illustration work -- it stops large flat areas looking like a
    screenshot of a colour swatch."""
    img = Image.new("RGB", (w, h), tone)
    if grain:
        rnd = random.Random(7)
        px = img.load()
        for _ in range((w * h) // 320):
            x, y = rnd.randrange(w), rnd.randrange(h)
            r, g, b = px[x, y]
            px[x, y] = (max(0, r - 7), max(0, g - 7), max(0, b - 6))
    return img


def card(img, box, fill=CARD, radius=24, hairline=HAIR, width=1):
    """A raised surface. Tone step plus a hairline -- no shadow, ever."""
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(box, radius=radius, fill=fill)
    if hairline:
        d.rounded_rectangle(box, radius=radius, outline=hairline, width=width)


def text(img, xy, s, f, fill=INK, anchor=None, spacing=None):
    d = ImageDraw.Draw(img)
    if spacing is None:
        d.text(xy, s, font=f, fill=fill, anchor=anchor)
        return d.textbbox(xy, s, font=f, anchor=anchor)
    x, y = xy
    for line in s.split("\n"):
        d.text((x, y), line, font=f, fill=fill)
        y += spacing
    return (x, xy[1], x, y)


def load_pet(name, frame=0):
    with open(os.path.join(PETS, "%s_f%d.raw" % (name, frame)), "rb") as fh:
        data = fh.read()
    w, h = struct.unpack("<HH", data[:4])
    return Image.frombytes("RGBA", (w, h), data[4:4 + w * h * 4], "raw", "BGRA")


def pet_names():
    return sorted({os.path.basename(p)[:-len("_f0.raw")]
                   for p in glob.glob(os.path.join(PETS, "*_f0.raw"))})


def fit(im, target_h=None, target_w=None):
    if target_h:
        s = target_h / float(im.height)
    else:
        s = target_w / float(im.width)
    return im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))),
                     Image.LANCZOS if s < 1 else Image.NEAREST)


def specimen_row(img, names, y, x0, x1, height, label_font=None):
    """Pets laid out like a field-guide plate: evenly spaced, sitting on a
    common baseline, optionally captioned."""
    if not names:
        return
    pitch = (x1 - x0) / float(len(names))
    for i, name in enumerate(names):
        try:
            sprite = fit(load_pet(name), target_h=height)
        except (OSError, ValueError):
            continue
        cx = int(x0 + pitch * (i + 0.5))
        img.paste(sprite, (cx - sprite.width // 2, y - sprite.height), sprite)
        if label_font:
            d = ImageDraw.Draw(img)
            d.text((cx, y + 7), name.replace("-", " ").upper()[:9],
                   font=label_font, fill=MUTED, anchor="ma")


# ---------------------------------------------------------------- social ---

def social_preview(console_plate=None):
    """1280x640. Keep everything that matters inside a 60px margin: X and Slack
    render this at 1.91:1 and crop ~29px off each side."""
    W, H = 1280, 640
    img = paper(W, H)

    # right: the console, photographed, on a raised card
    plate_path = console_plate or os.path.join(IMG, "console.png")
    if os.path.exists(plate_path):
        plate = fit(Image.open(plate_path).convert("RGB"), target_h=474)
        # the photo has specular highlights on the plastic; ivory bottoms out at
        # #FAF9F5 in this system, so pull pure white back off the top
        plate = plate.point(lambda v: min(v, 249))
        cw = plate.width + 76
        cx0 = W - 70 - cw
        card(img, (cx0, 56, W - 70, 606), fill=CARD, radius=20)
        px0, py0 = cx0 + 38, 84
        img.paste(plate, (px0, py0))
        d = ImageDraw.Draw(img)
        d.rectangle((px0, py0, px0 + plate.width - 1, py0 + plate.height - 1),
                    outline=HAIR, width=1)
        d.text((cx0 + cw // 2, py0 + plate.height + 12), "running on the real thing",
               font=font(SANS_R, 17), fill=MUTED, anchor="ma")

    # left column
    x = 84
    d = ImageDraw.Draw(img)

    # THE one clay element: the rule that opens the page
    d.rectangle((x, 118, x + 96, 123), fill=CLAY)

    col = 620          # the text column, wide enough to keep the gap honest
    text(img, (x, 150), "Pocket Clawd", font(SERIF, 84))
    d.line((x, 268, x + col, 268), fill=HAIR, width=1)

    text(img, (x, 292),
         "Your Claude usage limits, live on a handheld\n"
         "games console that costs about the price of\n"
         "a takeaway.",
         font(SERIF, 31), fill=INK2, spacing=45)

    text(img, (x, 456), "There is a crab. He gets worried when you don't.",
         font(SERIF_I, 22), fill=MUTED)

    text(img, (x, 514), "BY SHELLPAYANT", font(SANS, 18), fill=INK2)
    d.line((x, 548, x + col, 548), fill=HAIR, width=1)
    names = pet_names()
    specimen_row(img, names[:14], 598, x, x + col, 34)

    return img


# --------------------------------------------------------------- anatomy ---

def anatomy():
    """The real screen, with the parts named. The single most useful picture
    for someone who has never seen this before."""
    shot = Image.open(os.path.join(SHOTS, "busy.png")).convert("RGB")
    scale = 2
    shot = shot.resize((shot.width * scale, shot.height * scale), Image.NEAREST)
    pad_l, pad_r, pad_t, pad_b = 300, 360, 70, 80
    W = shot.width + pad_l + pad_r
    H = shot.height + pad_t + pad_b
    img = paper(W, H)
    card(img, (pad_l - 22, pad_t - 22, pad_l + shot.width + 21,
               pad_t + shot.height + 21), fill=CARD, radius=20)
    img.paste(shot, (pad_l, pad_t))
    d = ImageDraw.Draw(img)
    d.rectangle((pad_l, pad_t, pad_l + shot.width - 1, pad_t + shot.height - 1),
                outline=HAIR, width=1)

    f = font(SERIF, 25)
    fs = font(SANS_R, 18)

    # (label, second line, anchor point on the screenshot in 640x480 space, side)
    notes = [
        ("Your 5-hour window", "resets on the clock shown", (300, 105), "left"),
        ("This week", "across everything", (300, 190), "left"),
        ("This week, one model", "the limit that bites first", (300, 278), "left"),
        ("The last hour", "so you can see it climbing", (150, 400), "left"),
        ("One friend per project", "X3 means three terminals open", (470, 430), "right"),
        ("Clawd", "worried when you are", (455, 390), "right"),
    ]
    for title, sub, (sx, sy), side in notes:
        ax = pad_l + sx * scale
        ay = pad_t + sy * scale
        if side == "left":
            tx = pad_l - 40
            d.line((tx, ay, ax, ay), fill=HAIR, width=1)
            d.ellipse((ax - 4, ay - 4, ax + 4, ay + 4), fill=CLAY if title == "Clawd" else HAIR)
            d.text((tx - 8, ay - 30), title, font=f, fill=INK, anchor="ra")
            d.text((tx - 8, ay + 2), sub, font=fs, fill=MUTED, anchor="ra")
        else:
            tx = pad_l + shot.width + 40
            d.line((ax, ay, tx, ay), fill=HAIR, width=1)
            d.ellipse((ax - 4, ay - 4, ax + 4, ay + 4), fill=CLAY if title == "Clawd" else HAIR)
            d.text((tx + 8, ay - 30), title, font=f, fill=INK)
            d.text((tx + 8, ay + 2), sub, font=fs, fill=MUTED)

    d.text((W // 2, H - 46), "WHAT YOU'RE LOOKING AT", font=font(SANS, 18),
           fill=INK2, anchor="ma")
    return img


# ---------------------------------------------------------- how it works ---

def how_it_works():
    W, H = 1240, 470
    img = paper(W, H)
    d = ImageDraw.Draw(img)

    text(img, (60, 48), "How it gets there", font(SERIF, 44))
    d.line((60, 118, W - 60, 118), fill=HAIR, width=1)

    boxes = [
        (60, 160, 400, 380, CARD, "Your computer",
         "Claude Code is already\nlogged in here. A small\nscript reads how much\nyou've used.", None),
        (450, 160, 790, 380, OAT, "Your network",
         "The console announces\nitself. Nothing to\nconfigure, no address\nto type in.", None),
        (840, 160, 1180, 380, CARD, "The console",
         "Draws the numbers, and\nthe crab. Updates every\nminute or so.", None),
    ]
    for x0, y0, x1, y1, fill, title, body, _ in boxes:
        card(img, (x0, y0, x1, y1), fill=fill, radius=20)
        text(img, (x0 + 28, y0 + 26), title, font(SERIF, 28))
        text(img, (x0 + 28, y0 + 74), body, font(SANS_R, 19), fill=INK2, spacing=27)

    for ax in (412, 802):
        d.line((ax, 270, ax + 26, 270), fill=MUTED, width=2)
        d.polygon([(ax + 26, 264), (ax + 38, 270), (ax + 26, 276)], fill=MUTED)

    # THE one clay element
    d.rectangle((60, 412, 66, 446), fill=CLAY)
    text(img, (82, 410), "Or skip the computer entirely \u2014 the console can ask Anthropic itself,",
         font(SERIF, 21), fill=INK)
    text(img, (82, 438), "which works anywhere it has internet.", font(SERIF, 21), fill=INK)
    return img


# -------------------------------------------------------------- controls ---

def controls():
    W, H = 1080, 700
    img = paper(W, H)
    d = ImageDraw.Draw(img)
    text(img, (60, 44), "The buttons", font(SERIF, 44))
    d.line((60, 114, W - 60, 114), fill=HAIR, width=1)

    rows = [
        ("A", "Clawd says something"),
        ("B", "He tosses his friends in the air to show them off"),
        ("X / Y", "Dance / wave"),
        ("L1 / R1", "Zoom the chart out and in"),
        ("L2", "Play the anthem"),
        ("D-pad", "Show off each mood"),
        ("Left stick", "Walk him around the tank"),
        ("SELECT + START", "Exit"),
    ]
    y = 150
    fk = font(SANS, 21)
    fv = font(SERIF, 23)
    for k, v in rows:
        card(img, (60, y, 300, y + 44), fill=CARD, radius=10)
        d.text((180, y + 22), k, font=fk, fill=INK, anchor="mm")
        d.text((330, y + 22), v, font=fv, fill=INK2, anchor="lm")
        y += 52

    foot = y + 26
    d.rectangle((60, foot, 66, foot + 34), fill=CLAY)
    text(img, (82, foot - 2), "Buttons doing the wrong thing? Run clawd.py --map-buttons",
         font(SERIF, 20), fill=INK)
    text(img, (82, foot + 24), "and press each one when asked.", font(SERIF, 20), fill=INK)
    return img


# ------------------------------------------------------------------ main ---

def check_social(img):
    """Assert the things that are easy to get wrong and hard to notice."""
    problems = []
    if img.size != (1280, 640):
        problems.append("size is %dx%d, must be 1280x640" % img.size)

    colours = img.convert("RGB").getcolors(maxcolors=1 << 24) or []
    total = img.width * img.height
    # A few pure-white pixels are the pets' eyes -- illustration, not a surface.
    # The rule that matters is that no *surface* is pure white, so only complain
    # when there's enough of it to be one.
    whites = sum(n for n, c in colours if c == (255, 255, 255))
    if whites > total * 0.001:
        problems.append("%d pure-white pixels: a surface is #FFFFFF, "
                        "ivory bottoms out at #FAF9F5" % whites)

    # clay is reserved for one element; a big clay area means it crept into
    # decoration somewhere
    clay = sum(n for n, c in colours if c == CLAY)
    if clay > total * 0.02:
        problems.append("clay covers %.1f%% of the image; it is for one element"
                        % (100.0 * clay / total))
    return problems


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", choices=("social", "anatomy", "how", "controls"))
    ap.add_argument("--console", help="path to the processed console photo")
    args = ap.parse_args()

    os.makedirs(IMG, exist_ok=True)
    jobs = {
        "social": ("social-preview.png", lambda: social_preview(args.console)),
        "anatomy": ("anatomy.png", anatomy),
        "how": ("how-it-works.png", how_it_works),
        "controls": ("controls.png", controls),
    }
    for key, (name, fn) in jobs.items():
        if args.only and args.only != key:
            continue
        img = fn()
        path = os.path.join(IMG, name)
        img.save(path, optimize=True)
        size_kb = os.path.getsize(path) // 1024
        note = ""
        if key == "social":
            problems = check_social(img)
            note = ("  [%s]" % "; ".join(problems)) if problems else "  [checks pass]"
            if size_kb > 1000:
                note += "  [OVER 1MB - GitHub will reject it]"
        print("wrote %-22s %4dx%-4d %5d KB%s"
              % (name, img.width, img.height, size_kb, note))
    return 0


if __name__ == "__main__":
    sys.exit(main())
