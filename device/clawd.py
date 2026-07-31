#!/usr/bin/env python3
"""Pocket Clawd: a Claude-usage virtual pet drawn straight to the framebuffer.

Reads a small JSON file kept fresh by netd.py (see NETWORKING.md for the four
ways that file can arrive) and renders a 640x480 dashboard with a crab in it.

Exit: hold SELECT+START.  Run with --help for the setup flags.
"""
import colorsys
import json
import math
import os
import random
import select
import shutil
import struct
import subprocess
import sys
import time

try:
    import fcntl
except ImportError:
    fcntl = None

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import clawd_config  # noqa: E402  (must follow the sys.path line above)

HERE = clawd_config.HERE
APP = clawd_config.APP

# Simulator mode: runs the exact same rendering on a PC (no fb, no gamepad),
# dumping frames to a GIF or PNGs for preview before deploying.
SIM = os.name == "nt" or bool(os.environ.get("CLAWD_SIM"))

# The layout is designed at 640x480. Screen letterboxes this onto bigger
# panels; smaller ones get an explanation instead of a scrambled screen.
W, H = 640, 480


state_dir = clawd_config.state_dir
CFG = clawd_config.load_config()

FB = CFG["fb"]
DATA = clawd_config.data_path(CFG)
HIST = clawd_config.hist_path(CFG)
PETS_DIR = os.path.join(HERE, "pets")
QUIPS_FILE = os.path.join(HERE, "quips.txt")

if SIM:
    _base = os.environ.get("CLAWD_SIM_DIR", os.path.join(HERE, "..", "sim"))
    _base = os.path.abspath(_base)
    DATA = os.path.join(_base, "sim_usage.json")
    HIST = os.path.join(_base, "sim_hist.jsonl")
    PETS_DIR = os.environ.get("CLAWD_SIM_PETS", PETS_DIR)


def load_pets():
    """pets/<name>_f<k>.raw -> {name: [frame0, frame1, ...]}
    where each frame is (w, h, [(dy, dx, bgra_bytes), ...]). Plain
    <name>.raw files load as single-frame pets."""
    frames = {}
    try:
        files = os.listdir(PETS_DIR)
    except OSError:
        return {}
    for fn in sorted(files):
        if not fn.endswith(".raw"):
            continue
        try:
            data = open(os.path.join(PETS_DIR, fn), "rb").read()
            w, h = struct.unpack("<HH", data[:4])
            px = memoryview(data)[4:]
            runs = []
            for yy in range(h):
                row = yy * w * 4
                xx = 0
                while xx < w:
                    if px[row + xx * 4 + 3]:
                        x0 = xx
                        while xx < w and px[row + xx * 4 + 3]:
                            xx += 1
                        runs.append((yy, x0, bytes(px[row + x0 * 4:row + xx * 4])))
                    else:
                        xx += 1
            base = fn[:-4]
            if "_f" in base:
                base = base.rsplit("_f", 1)[0]
            frames.setdefault(base, []).append((w, h, runs))
        except (OSError, struct.error):
            pass
    return frames


# Official clawd-pet artwork (MIT, @abderrahimghazali): used for the aquarium
# friends. USE_PET_SKIN swaps the main crab for the artwork too (off: the
# procedural pixel crab stays protagonist).
PETS = load_pets()
USE_PET_SKIN = False

BG = (12, 13, 22)
PANEL = (27, 27, 40)
EDGE = (92, 92, 122)
EDGE_HI = (138, 138, 180)
TRACK = (44, 44, 58)
FG = (245, 242, 234)
DIM = (158, 156, 148)
ACCENT = (250, 128, 88)
HALO = (118, 54, 34)
CHIP_BG = (44, 44, 62)
CHIP_FG = (196, 196, 232)
GOOD = (86, 214, 122)
WARN = (255, 188, 46)
BAD = (255, 88, 72)
CYAN = (112, 216, 236)

THROW_TIME = 0.9      # how long Clawd holds the throwing pose

CORAL = (242, 132, 92)
CORAL_D = (164, 78, 50)
CLAW = (224, 114, 78)
CHEEK = (255, 176, 152)

FONT = {
    'A': [0x0E,0x11,0x11,0x1F,0x11,0x11,0x11], 'B': [0x1E,0x11,0x11,0x1E,0x11,0x11,0x1E],
    'C': [0x0E,0x11,0x10,0x10,0x10,0x11,0x0E], 'D': [0x1E,0x11,0x11,0x11,0x11,0x11,0x1E],
    'E': [0x1F,0x10,0x10,0x1E,0x10,0x10,0x1F], 'F': [0x1F,0x10,0x10,0x1E,0x10,0x10,0x10],
    'G': [0x0E,0x11,0x10,0x17,0x11,0x11,0x0F], 'H': [0x11,0x11,0x11,0x1F,0x11,0x11,0x11],
    'I': [0x0E,0x04,0x04,0x04,0x04,0x04,0x0E], 'J': [0x07,0x02,0x02,0x02,0x02,0x12,0x0C],
    'K': [0x11,0x12,0x14,0x18,0x14,0x12,0x11], 'L': [0x10,0x10,0x10,0x10,0x10,0x10,0x1F],
    'M': [0x11,0x1B,0x15,0x15,0x11,0x11,0x11], 'N': [0x11,0x19,0x15,0x13,0x11,0x11,0x11],
    'O': [0x0E,0x11,0x11,0x11,0x11,0x11,0x0E], 'P': [0x1E,0x11,0x11,0x1E,0x10,0x10,0x10],
    'Q': [0x0E,0x11,0x11,0x11,0x15,0x12,0x0D], 'R': [0x1E,0x11,0x11,0x1E,0x14,0x12,0x11],
    'S': [0x0F,0x10,0x10,0x0E,0x01,0x01,0x1E], 'T': [0x1F,0x04,0x04,0x04,0x04,0x04,0x04],
    'U': [0x11,0x11,0x11,0x11,0x11,0x11,0x0E], 'V': [0x11,0x11,0x11,0x11,0x11,0x0A,0x04],
    'W': [0x11,0x11,0x11,0x15,0x15,0x1B,0x11], 'X': [0x11,0x11,0x0A,0x04,0x0A,0x11,0x11],
    'Y': [0x11,0x11,0x0A,0x04,0x04,0x04,0x04], 'Z': [0x1F,0x01,0x02,0x04,0x08,0x10,0x1F],
    '0': [0x0E,0x11,0x13,0x15,0x19,0x11,0x0E], '1': [0x04,0x0C,0x04,0x04,0x04,0x04,0x0E],
    '2': [0x0E,0x11,0x01,0x06,0x08,0x10,0x1F], '3': [0x0E,0x11,0x01,0x06,0x01,0x11,0x0E],
    '4': [0x02,0x06,0x0A,0x12,0x1F,0x02,0x02], '5': [0x1F,0x10,0x1E,0x01,0x01,0x11,0x0E],
    '6': [0x06,0x08,0x10,0x1E,0x11,0x11,0x0E], '7': [0x1F,0x01,0x02,0x04,0x08,0x08,0x08],
    '8': [0x0E,0x11,0x11,0x0E,0x11,0x11,0x0E], '9': [0x0E,0x11,0x11,0x0F,0x01,0x02,0x0C],
    '%': [0x19,0x19,0x02,0x04,0x08,0x13,0x13], ':': [0x00,0x0C,0x0C,0x00,0x0C,0x0C,0x00],
    '.': [0x00,0x00,0x00,0x00,0x00,0x0C,0x0C], '-': [0x00,0x00,0x00,0x1F,0x00,0x00,0x00],
    '(': [0x02,0x04,0x08,0x08,0x08,0x04,0x02], ')': [0x08,0x04,0x02,0x02,0x02,0x04,0x08],
    '/': [0x01,0x01,0x02,0x04,0x08,0x10,0x10], '+': [0x00,0x04,0x04,0x1F,0x04,0x04,0x00],
    '!': [0x04,0x04,0x04,0x04,0x04,0x00,0x04], '?': [0x0E,0x11,0x01,0x02,0x04,0x00,0x04],
    '=': [0x00,0x1F,0x00,0x1F,0x00,0x00,0x00],
    "'": [0x04,0x04,0x00,0x00,0x00,0x00,0x00],
    ',': [0x00,0x00,0x00,0x00,0x00,0x0C,0x08],
    '_': [0x00,0x00,0x00,0x00,0x00,0x00,0x1F],
    '"': [0x0A,0x0A,0x00,0x00,0x00,0x00,0x00],
    '*': [0x00,0x0A,0x04,0x1F,0x04,0x0A,0x00],
    '#': [0x0A,0x1F,0x0A,0x0A,0x1F,0x0A,0x00],
    '&': [0x0C,0x12,0x14,0x08,0x15,0x12,0x0D],
    '>': [0x08,0x04,0x02,0x01,0x02,0x04,0x08],
    '<': [0x02,0x04,0x08,0x10,0x08,0x04,0x02],
    ';': [0x00,0x0C,0x0C,0x00,0x0C,0x08,0x00],
    ' ': [0, 0, 0, 0, 0, 0, 0],
}

# Button codes differ between handhelds more than you'd hope. These defaults
# cover the standard Linux gamepad codes plus what this class of RK3326 clone
# actually emits -- its SELECT/START arrive as BTN_TRIGGER_HAPPY1/2 (704/705)
# rather than BTN_SELECT/BTN_START (314/315). If a device disagrees, run
# `clawd.py --map-buttons` and the wizard writes the right codes to config.json.
# Button codes are positional, not by label: BTN_SOUTH is the bottom button and
# BTN_EAST the right-hand one. Retro handhelds label those Nintendo-style, so
# the right-hand button is A and the bottom one is B -- the opposite of an Xbox
# pad. These defaults follow the handheld convention, which is what this whole
# class of device uses.
DEFAULT_BUTTONS = {
    "select":   [314, 704],
    "start":    [315, 705],
    "talk":     [305],   # A, the right-hand button  (BTN_EAST)
    "shuffle":  [304],   # B, the bottom button      (BTN_SOUTH)
    "dance":    [307],   # X, the top button         (BTN_NORTH)
    "wave":     [308],   # Y, the left-hand button   (BTN_WEST)
    "zoom_in":  [310],   # L1 / BTN_TL
    "zoom_out": [311],   # R1 / BTN_TR
    "song":     [312],   # L2 / BTN_TL2
    "up":       [544],   # BTN_DPAD_UP  (many pads use ABS_HAT0Y instead --
    "down":     [545],   # BTN_DPAD_DOWN  the hat axes are handled separately)
    "left":     [546],
    "right":    [547],
}

# Axis codes we care about
ABS_X, ABS_Z, ABS_RZ, ABS_HAT0X, ABS_HAT0Y = 0, 2, 5, 16, 17


class ButtonMap:
    """action name <-> event code, with user overrides from config.json."""

    def __init__(self, overrides=None):
        self.by_action = {k: list(v) for k, v in DEFAULT_BUTTONS.items()}
        for name, codes in (overrides or {}).items():
            if isinstance(codes, int):
                codes = [codes]
            if not codes or isinstance(codes, str):
                continue
            try:
                self.by_action[name] = [int(c) for c in codes]
            except (TypeError, ValueError):
                pass          # a typo in config.json keeps the defaults
        self.by_code = {}
        for action, codes in self.by_action.items():
            for c in codes:
                self.by_code.setdefault(int(c), action)

    def action(self, code):
        return self.by_code.get(code)

BODY = [
    "....oooooooooooo....",
    "..oo############oo..",
    ".o################o.",
    "o##################o",
    "o##################o",
    "o##################o",
    "o##################o",
    "o##################o",
    "o##################o",
    "o##################o",
    ".o################o.",
    "..oo############oo..",
    "....oooooooooooo....",
]
CLAW_L = [  # open pincer facing outward-left
    "..oooo.",
    ".o####o",
    "o##oo..",
    "o##o...",
    "o##oo..",
    ".o####o",
    "..oooo.",
]


FBIOGET_VSCREENINFO = 0x4600
FBIOPUT_VSCREENINFO = 0x4601
FBIOGET_FSCREENINFO = 0x4602
FBIOPAN_DISPLAY = 0x4606

# struct fb_fix_screeninfo, native sizes/alignment. The explicit trailing H is
# the compiler's pad before line_length, which keeps the offsets right on both
# 32- and 64-bit userlands.
FIX_FMT = "@16sLIIIIHHHHI"

# In struct fb_var_screeninfo: xres, yres, xres_virtual, yres_virtual,
# xoffset, yoffset, bits_per_pixel -- the first seven __u32.
VAR_FMT = "<IIIIIII"


class PanelUnsupported(Exception):
    """Raised when the panel can't display the 640x480 layout at all."""


def probe_panel(fd):
    """Real geometry of the framebuffer. Returns (w, h, bpp, stride, smem_len).

    The old code called FBIOGET_VSCREENINFO and then threw the answer away in
    favour of hardcoded constants, which is why a different panel produced a
    sheared image rather than a message."""
    w = h = bpp = stride = smem = 0
    try:
        v = bytearray(160)
        fcntl.ioctl(fd, FBIOGET_VSCREENINFO, v)
        w, h, _xv, _yv, _xo, _yo, bpp = struct.unpack_from(VAR_FMT, v, 0)
    except (OSError, struct.error):
        pass
    try:
        n = struct.calcsize(FIX_FMT)
        fx = bytearray(n)
        fcntl.ioctl(fd, FBIOGET_FSCREENINFO, fx)
        vals = struct.unpack_from(FIX_FMT, fx, 0)
        smem, stride = vals[2], vals[10]
    except (OSError, struct.error):
        pass
    # sysfs fallbacks for drivers that dislike the ioctls
    if not (w and h):
        try:
            with open("/sys/class/graphics/fb0/virtual_size") as f:
                w, h = [int(x) for x in f.read().strip().split(",")[:2]]
        except (OSError, ValueError):
            pass
    if not bpp:
        try:
            with open("/sys/class/graphics/fb0/bits_per_pixel") as f:
                bpp = int(f.read().strip())
        except (OSError, ValueError):
            bpp = 32
    if not stride:
        stride = w * (bpp // 8) if w and bpp else W * 4
    return w or W, h or H, bpp or 32, stride, smem


class Screen:
    def __init__(self, logical=None, plain=False):
        self.w, self.h = logical or (W, H)
        self.stride = self.w * 4          # internal buffer is always tight BGRA
        self.buf = bytearray(self.stride * self.h)
        self.pages = 1
        self.page = 0
        self.var = None
        self.out = None                   # device-sized compose buffer, if needed
        self.on_frame = None              # live viewer callback (desktop app)
        self.ox = self.oy = 0
        self.plain = plain
        if SIM:
            self.fb = None
            self.frames = []
            # CLAWD_SIM_PANEL=1280x720 (optionally @16) pretends the panel is a
            # different shape, so the letterbox and refusal paths are testable
            # without owning eight handhelds.
            self.dev_w, self.dev_h, self.dev_bpp = self.w, self.h, 32
            spec = os.environ.get("CLAWD_SIM_PANEL")
            if spec:
                geom, _, depth = spec.partition("@")
                try:
                    dw, dh = [int(v) for v in geom.lower().split("x")[:2]]
                    self.dev_w, self.dev_h = dw, dh
                    self.dev_bpp = int(depth) if depth else 32
                except ValueError:
                    pass
            self.dev_stride = self.dev_w * 4
            if logical is None:
                self._check_panel()
            self.ox = (self.dev_w - self.w) // 2
            self.oy = (self.dev_h - self.h) // 2
            if self.ox or self.oy or self.dev_stride != self.stride:
                self.out = bytearray(self.dev_stride * self.dev_h)
                edge = struct.pack("<BBBB", BG[2], BG[1], BG[0], 0)
                self.out[:] = edge * (len(self.out) // 4)
            self.template = self._make_bg()
            return
        self.fb = open(FB, "r+b", buffering=0)
        fd = self.fb.fileno()
        self.dev_w, self.dev_h, self.dev_bpp, self.dev_stride, smem = probe_panel(fd)
        if logical is None:
            self._check_panel()
        # centre the 640x480 layout on anything larger
        self.ox = (self.dev_w - self.w) // 2
        self.oy = (self.dev_h - self.h) // 2
        direct = (self.ox == 0 and self.oy == 0
                  and self.dev_stride == self.stride)
        if not direct:
            self.out = bytearray(self.dev_stride * self.dev_h)
            edge = struct.pack("<BBBB", BG[2], BG[1], BG[0], 0)
            self.out[:] = edge * (len(self.out) // 4)
        self.template = self._make_bg()
        # Double buffering via panning kills tearing. Only if the driver both
        # accepts a taller virtual screen AND actually has the memory for it --
        # the old code never checked smem_len and could write past the mapping.
        try:
            need = self.dev_stride * self.dev_h * 2
            if smem and smem < need:
                raise OSError("framebuffer too small for two pages")
            v = bytearray(160)
            fcntl.ioctl(fd, FBIOGET_VSCREENINFO, v)
            if struct.unpack_from("<I", v, 12)[0] < self.dev_h * 2:
                struct.pack_into("<I", v, 12, self.dev_h * 2)  # yres_virtual
                fcntl.ioctl(fd, FBIOPUT_VSCREENINFO, v)
                fcntl.ioctl(fd, FBIOGET_VSCREENINFO, v)
            if struct.unpack_from("<I", v, 12)[0] >= self.dev_h * 2:
                self.pages = 2
                self.var = v
        except OSError:
            self.pages = 1

    def _check_panel(self):
        if self.dev_bpp != 32:
            raise PanelUnsupported("%dx%d at %d bits per pixel"
                                   % (self.dev_w, self.dev_h, self.dev_bpp))
        if self.dev_w < self.w or self.dev_h < self.h:
            raise PanelUnsupported("%dx%d is smaller than %dx%d"
                                   % (self.dev_w, self.dev_h, self.w, self.h))

    @property
    def frame_size(self):
        """Size of what flush() emits -- device size when letterboxing."""
        if self.out is None:
            return self.w, self.h
        return self.dev_w, self.dev_h

    def describe(self):
        mode = "direct" if self.out is None else "letterboxed"
        return "%dx%d %dbpp stride=%d %s pages=%d" % (
            self.dev_w, self.dev_h, self.dev_bpp, self.dev_stride,
            mode, self.pages)

    def reset_pan(self):
        if self.var is not None:
            try:
                struct.pack_into("<I", self.var, 20, 0)
                fcntl.ioctl(self.fb.fileno(), FBIOPAN_DISPLAY, self.var)
            except OSError:
                pass

    def _make_bg(self):
        # vertical gradient + faint scanlines + sparse stars, built once
        W, H = self.w, self.h
        tpl = bytearray(self.stride * H)
        pad = b""
        top, bot = (18, 19, 38), (52, 42, 84)
        if self.plain:
            row = struct.pack("<BBBB", BG[2], BG[1], BG[0], 0) * W
            for y in range(H):
                tpl[y * self.stride:(y + 1) * self.stride] = row
            return bytes(tpl)
        for y in range(H):
            f = y / (H - 1)
            r = int(top[0] + (bot[0] - top[0]) * f)
            g = int(top[1] + (bot[1] - top[1]) * f)
            b = int(top[2] + (bot[2] - top[2]) * f)
            if y % 4 == 3:
                r, g, b = max(0, r - 5), max(0, g - 5), max(0, b - 5)
            row = struct.pack("<BBBB", b, g, r, 0) * W + pad
            tpl[y * self.stride:(y + 1) * self.stride] = row
        rnd = random.Random(36)  # fixed seed: stars don't shimmer
        for _ in range(130):
            sx, sy = rnd.randrange(4, W - 4), rnd.randrange(4, H - 4)
            roll = rnd.random()
            if roll < 0.08:
                c = (250, 140, 100)   # coral star
            elif roll < 0.16:
                c = (120, 210, 230)   # cyan star
            else:
                v = rnd.choice((70, 92, 118))
                c = (v + 16, v + 4, v)
            off = sy * self.stride + sx * 4
            tpl[off:off + 4] = struct.pack("<BBBB", c[2], c[1], c[0], 0)
            if roll < 0.16:  # colored stars get a tiny cross
                for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    o2 = (sy + dy) * self.stride + (sx + dx) * 4
                    tpl[o2:o2 + 4] = struct.pack(
                        "<BBBB", c[2] // 2, c[1] // 2, c[0] // 2, 0)
        return bytes(tpl)

    def clear(self, c=None):
        self.buf[:] = self.template

    def rect(self, x, y, w, h, c):
        x, y, w, h = int(x), int(y), int(w), int(h)
        if x < 0:
            w += x
            x = 0
        if y < 0:
            h += y
            y = 0
        w, h = min(w, self.w - x), min(h, self.h - y)
        if w <= 0 or h <= 0:
            return
        px = struct.pack("<BBBB", c[2], c[1], c[0], 0) * w
        st = self.stride
        buf = self.buf
        for yy in range(y, y + h):
            off = yy * st + x * 4
            buf[off:off + w * 4] = px

    def frame(self, x, y, w, h, c, t=2):
        self.rect(x, y, w, t, c)
        self.rect(x, y + h - t, w, t, c)
        self.rect(x, y, t, h, c)
        self.rect(x + w - t, y, t, h, c)

    def text(self, x, y, s, c, scale=2):
        cx = int(x)
        y = int(y)
        for ch in s.upper():
            g = FONT.get(ch, FONT['?'])
            for ry, bits in enumerate(g):
                rx = 0
                while rx < 5:
                    if bits & (0x10 >> rx):
                        run = 1
                        while rx + run < 5 and bits & (0x10 >> (rx + run)):
                            run += 1
                        self.rect(cx + rx * scale, y + ry * scale,
                                  run * scale, scale, c)
                        rx += run
                    else:
                        rx += 1
            cx += 6 * scale
        return cx

    def text_w(self, s, scale=2):
        return len(s) * 6 * scale

    def sprite(self, x, y, rows, sc, colors):
        for ry, row in enumerate(rows):
            rx = 0
            n = len(row)
            while rx < n:
                ch = row[rx]
                if ch == '.':
                    rx += 1
                    continue
                run = 1
                while rx + run < n and row[rx + run] == ch:
                    run += 1
                self.rect(x + rx * sc, y + ry * sc, run * sc, sc, colors[ch])
                rx += run

    def blit(self, x, y, pet):
        w, h, runs = pet
        x, y = int(x), int(y)
        st = self.stride
        buf = self.buf
        for dy, dx, b in runs:
            yy = y + dy
            if yy < 0 or yy >= self.h:
                continue
            xx = x + dx
            n = len(b) // 4
            if xx >= self.w or xx + n <= 0:
                continue
            if xx < 0:
                b = b[-xx * 4:]
                n += xx
                xx = 0
            if xx + n > self.w:
                b = b[:(self.w - xx) * 4]
                n = self.w - xx
            off = yy * st + xx * 4
            buf[off:off + n * 4] = b

    def _compose(self):
        """Centre the 640x480 image inside a device-sized buffer. Only used
        when the panel is bigger than the layout; the common case writes
        self.buf straight out."""
        if self.out is None:
            return self.buf
        src_stride, dst_stride = self.stride, self.dev_stride
        out, buf = self.out, self.buf
        x4 = self.ox * 4
        for y in range(self.h):
            so = y * src_stride
            do = (y + self.oy) * dst_stride + x4
            out[do:do + src_stride] = buf[so:so + src_stride]
        return out

    def flush(self):
        if SIM:
            frame = bytes(self._compose())
            if self.on_frame is not None:
                # a live viewer (the desktop app) takes each frame as it comes;
                # accumulating them all is what the GIF path wants, but at
                # 640x480x4 it costs ~1.2MB a frame and would grow forever
                self.on_frame(frame, self.frame_size)
            else:
                self.frames.append(frame)
            return
        data = self._compose()
        if self.pages > 1:
            page = 1 - self.page
            try:
                self.fb.seek(page * self.dev_stride * self.dev_h)
                self.fb.write(data)
                struct.pack_into("<I", self.var, 20, page * self.dev_h)
                fcntl.ioctl(self.fb.fileno(), FBIOPAN_DISPLAY, self.var)
                self.page = page
                return
            except OSError:
                self.pages = 1
        self.fb.seek(0)
        self.fb.write(data)


def draw_title(scr, anim_elapsed):
    """Header: rainbow wave for ~3s (startup + every 5 min), then calm glow."""
    title = "CLAUDE USAGE"
    x0 = (W - scr.text_w(title, 4)) // 2
    if anim_elapsed is None or anim_elapsed > 3.0:
        glow_text(scr, x0, 18, title, 4)
        return
    damp = max(0.0, 1.0 - anim_elapsed / 3.0)
    cx = x0
    for i, ch in enumerate(title):
        ph = anim_elapsed * 5 - i * 0.45
        yoff = int(math.sin(ph) * 9 * damp) if ph > 0 else 0
        r, g, b = colorsys.hsv_to_rgb(
            (anim_elapsed * 0.45 + i * 0.055) % 1.0, 0.75, 1.0)
        col = tuple(int(c * 255 * damp + a * (1 - damp))
                    for c, a in zip((r, g, b), ACCENT))
        for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
            scr.text(cx + dx, 18 + dy + yoff, ch, HALO, 4)
        scr.text(cx, 18 + yoff, ch, col, 4)
        cx += 24


def glow_text(scr, x, y, s, scale):
    for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2), (-1, -1), (1, 1), (-1, 1), (1, -1)):
        scr.text(x + dx, y + dy, s, HALO, scale)
    scr.text(x, y, s, ACCENT, scale)


def chip(scr, x, y, label):
    w = scr.text_w(label, 1) + 8
    scr.rect(x, y, w, 13, CHIP_BG)
    scr.frame(x, y, w, 13, EDGE, 1)
    scr.text(x + 4, y + 3, label, CHIP_FG, 1)
    return w


def panel(scr, x, y, w, h, label):
    scr.rect(x, y, w, h, PANEL)
    scr.frame(x, y, w, h, EDGE, 2)
    for cx, cy in ((x, y), (x + w - 8, y), (x, y + h - 8), (x + w - 8, y + h - 8)):
        scr.rect(cx, cy, 8, 2, EDGE_HI)
        scr.rect(cx, cy, 2, 8, EDGE_HI)
        scr.rect(cx + 6, cy, 2, 8, EDGE_HI)
        scr.rect(cx, cy + 6, 8, 2, EDGE_HI)
    if label:
        chip(scr, x + 10, y - 6, label)


def pct_color(p):
    if p >= 85:
        return BAD
    if p >= 60:
        return WARN
    return GOOD


DEFAULT_QUIPS = [
    "HI! I AM CLAWD",
    "TOKENS GO BRRR",
    "SNIP SNIP!",
    "I LIVE HERE NOW",
    "TOUCH GRASS BETWEEN PROMPTS",
    "ALL SYSTEMS CORAL",
    "PRESS X = DANCE",
    "PRESS Y = WAVE",
    "PRESS L2 = A SONG",
    "DRAWN PIXEL BY PIXEL",
    "NO CLOUD. JUST CRAB.",
    "SHIPPING BEATS PERFECT",
    "THEY SHIPPING THEY SHIPPING",
    "BAD CHANGE!",
    "LOOKS GOOD TO ME",
    "I START MY DAY IN PLAN MODE",
    "WATCH THE CONTEXT WINDOW",
    "MAKE ANOTHER .MD",
    "BEEN HERE SINCE 2.0",
    "THERE ARE LEVELS TO PROMPTING",
    "ULTRATHINK!",
    "TIME TO ULTRATHINK",
    "ULTRACODE ENGAGED",
    "SERVER DOWN CAUSE MCP",
    "ITS JUST NOT CC",
    "ORCHESTRATION MADE ME TEAM LEAD",
]


def load_quips():
    """quips.txt, one per line, # for comments. Write your own -- the font
    only has A-Z 0-9 and a little punctuation, so keep it shouty."""
    try:
        with open(QUIPS_FILE, encoding="utf-8") as f:
            lines = [l.strip() for l in f]
        got = [l for l in lines if l and not l.startswith("#")]
        if got:
            return got
    except OSError:
        pass
    return list(DEFAULT_QUIPS)


QUIPS = load_quips()


class Clawd:
    def __init__(self, x, floor, sc=5):
        self.x = float(x)
        self.floor = floor
        self.sc = sc            # pixel size of one sprite cell
        self.tx = float(x)
        self.next_blink = time.time() + 3
        self.blink_until = 0
        self.next_move = time.time() + 6
        self.next_look = time.time() + 2
        self.pupil = (0, 0)
        self.pcur = [0.0, 0.0]
        self.wave_until = 0
        self.jump_until = 0
        self.dance_until = 0
        self.bubble = None  # (lines, until)
        self.next_auto = time.time() + 20
        self.ctx = None
        self.sleeping = False
        self.disconnected = False
        self.celebrate_until = 0
        self.stick_until = 0     # joystick control active
        self.forced_mood = None  # (mood, until) via d-pad showcase
        self.force_sleep_until = 0
        self.throw_until = 0     # claws up, launching the tank friends
        self._bag = []           # quips dealt without replacement
        self._bag_of = 0

    def poke(self):  # fresh data arrived
        self.jump_until = time.time() + 0.6
        self.celebrate_until = time.time() + 1.5

    def say(self, text):
        words = text.upper().split()
        lines, cur = [], ""
        for wd in words:
            if len(cur) + len(wd) + 1 > 16 and cur:
                lines.append(cur)
                cur = wd
            else:
                cur = (cur + " " + wd).strip()
        if cur:
            lines.append(cur)
        self.bubble = (lines[:3], time.time() + 4.5)

    def pick_quip(self):
        """Deal from a shuffled bag rather than picking at random.

        Uniform random meant the three rainbow ULTRATHINK/ULTRACODE lines were
        a 1-in-11 shot each time, so it was entirely possible to watch for ten
        minutes and never see one. Dealing without replacement guarantees every
        line shows up once per cycle."""
        pool = list(QUIPS)
        d = self.ctx
        if d:
            fh = int(d.get("five_hour_pct", 0))
            sd = int(d.get("seven_day_pct", 0))
            pool += [
                "5H WINDOW AT %d%%" % fh,
                "WEEKLY AT %d%%" % sd,
                "5H RESETS " + str(d.get("five_hour_reset", "?")),
            ]
            if sd >= 85:
                pool += ["WEEKLY IS SPICY!", "EASY ON THE TOKENS..."]
            elif fh < 25:
                pool += ["PLENTY OF RUNWAY", "FRESH WINDOW VIBES"]
            note = d.get("note")
            if note:
                pool += [note, note]
        # Refill when empty, or when the pool itself changed (new data brings
        # new context lines in and drops stale ones).
        if not self._bag or self._bag_of != len(pool):
            self._bag = list(pool)
            self._bag_of = len(pool)
            random.shuffle(self._bag)
        return self._bag.pop()

    def on_action(self, action):
        t = time.time()
        self.next_auto = t + 25
        if action == "talk":
            self.say(self.pick_quip())
        elif action == "dance":
            self.dance_until = t + 3.0
        elif action == "wave":
            self.wave_until = t + 2.2
        elif action == "up":       # showcase happy
            self.forced_mood = (0, t + 5)
        elif action == "right":    # showcase neutral
            self.forced_mood = (1, t + 5)
        elif action == "down":     # showcase worried
            self.forced_mood = (2, t + 5)
        elif action == "left":     # showcase sleeping
            self.force_sleep_until = t + 5
        # "shuffle" is handled in the main loop: it re-rolls the tank

    def auto_show(self):
        # dance is button-only -- too energetic for ambient mode
        act = random.random()
        if act < 0.72:            # mostly talking: that's the character
            self.say(self.pick_quip())
        elif act < 0.9:
            self.wave_until = time.time() + 2.2
        else:
            self.jump_until = time.time() + 0.6

    def update(self, xmin, xmax, idle_for):
        t = time.time()
        if t > self.next_blink:
            self.blink_until = t + 0.15
            self.next_blink = t + random.uniform(2.5, 6)
        if t > self.next_look:
            self.pupil = (random.randint(-2, 2), random.randint(-1, 1))
            self.next_look = t + random.uniform(1.5, 4)
        if t > self.next_move and t > self.dance_until:
            self.tx = random.uniform(xmin, xmax)
            self.next_move = t + random.uniform(30, 55)
        if idle_for > 8 and t > self.next_auto and not self.sleeping:
            self.auto_show()
            self.next_auto = t + random.uniform(10, 18)
        d = self.tx - self.x
        if abs(d) > 2 and t > self.dance_until:
            # constant whole-pixel speed: no fractional-step stutter
            self.x += 1.0 if d > 0 else -1.0
        self.pcur[0] += (self.pupil[0] - self.pcur[0]) * 0.15
        self.pcur[1] += (self.pupil[1] - self.pcur[1]) * 0.15
        if self.bubble and t > self.bubble[1]:
            self.bubble = None

    def draw_bubble(self, scr, x, y):
        t = time.time()
        lines = self.bubble[0]
        wmax = max(len(l) for l in lines)
        bw = wmax * 12 + 16
        bh = len(lines) * 16 + 12
        bx = min(max(8, x - bw // 3), W - bw - 8)
        by = max(8, y - bh - 14)
        scr.rect(bx, by, bw, bh, (238, 234, 226))
        scr.frame(bx, by, bw, bh, (120, 100, 90), 2)
        scr.rect(x + 10, by + bh, 8, 5, (238, 234, 226))
        scr.rect(x + 12, by + bh + 5, 4, 4, (238, 234, 226))
        for i, l in enumerate(lines):
            fancy_text(scr, bx + 8, by + 7 + i * 16, l, 2, t)

    def draw(self, scr, mood):
        t = time.time()
        sc = self.sc
        if self.forced_mood and t < self.forced_mood[1]:
            mood = self.forced_mood[0]
        slp = self.sleeping or t < self.force_sleep_until
        dancing = t < self.dance_until
        walking = (abs(self.tx - self.x) > 1 or t < self.stick_until) \
            and not dancing
        # gentle: bounce while walking/dancing, slow breathing when idle
        if dancing:
            bob = math.sin(t * 7) * 3
        elif walking:
            bob = math.sin(t * 6) * 2
        else:
            bob = math.sin(t * 1.1) * 1.6
        jump = 0
        if t < self.jump_until:
            ph = (self.jump_until - t) / 0.6
            jump = math.sin(ph * math.pi) * 14
        x = int(self.x + (math.sin(t * 3.5) * 3 if dancing else 0))
        y = int(self.floor - 13 * sc - 3 * sc + bob - jump)
        if USE_PET_SKIN and PETS:
            if self.disconnected:
                name = "disconnected"
            elif slp:
                name = "sleeping"
            elif t < self.celebrate_until or dancing:
                name = "celebrating"
            elif t < self.wave_until:
                name = "waving"
            elif mood == 2:
                name = "mindblown"
            elif mood == 1:
                name = "working-thinking"
            else:
                name = "happy"
            frames = PETS.get(name) or PETS.get("happy") or PETS.get("static-base")
            if frames:
                pet = frames[int(t * 8) % len(frames)]
                pw, ph = pet[0], pet[1]
                cx = x + 50
                scr.blit(cx - pw // 2, self.floor - ph + int(bob - jump), pet)
                if t < self.jump_until:
                    scr.text(cx + pw // 2 + 6, self.floor - ph - 10, "!", ACCENT, 3)
                if self.bubble:
                    self.draw_bubble(scr, cx - 40, self.floor - ph)
                return
        cmap = {'#': CORAL, 'o': CORAL_D, 'w': FG}
        waving = t < self.wave_until
        beat = (t * 5) % 2 < 1
        # arms + claws
        scr.rect(x - 2 * sc, y + 5 * sc, 3 * sc, 2 * sc, CORAL_D)
        scr.rect(x + 19 * sc, y + 5 * sc, 3 * sc, 2 * sc, CORAL_D)
        if dancing:
            lyl = y + (0 if beat else 4) * sc - 2 * sc
            lyr = y + (4 if beat else 0) * sc - 2 * sc
        elif waving:
            lyl = y + 2 * sc + (-2 * sc if beat else 0)
            lyr = y + 4 * sc
        elif t < self.throw_until:
            # both claws thrown upward, following the launch through
            k = 1.0 - (self.throw_until - t) / THROW_TIME
            up = int(math.sin(min(1.0, k * 1.6) * math.pi) * 3.2 * sc)
            lyl = lyr = y + 3 * sc - up
        else:
            lyl = lyr = y + 3 * sc
        scr.sprite(x - 8 * sc, lyl, CLAW_L, sc, {'#': CLAW, 'o': CORAL_D})
        scr.sprite(x + 21 * sc, lyr, [r[::-1] for r in CLAW_L], sc,
                   {'#': CLAW, 'o': CORAL_D})
        scr.sprite(x, y, BODY, sc, cmap)
        legph = int(t * 6) % 2 if walking else 0
        for i, lx in enumerate((3, 8, 13)):
            up = sc if (i % 2) == legph and walking else 0
            scr.rect(x + lx * sc, y + 13 * sc - up, 2 * sc, 2 * sc, CORAL_D)
            scr.rect(x + (16 - lx) * sc + 2 * sc, y + 13 * sc - up, 2 * sc, 2 * sc, CORAL_D)
        # big eyes
        exl, exr = x + 4 * sc, x + 12 * sc
        ey = y + 3 * sc
        blink = t < self.blink_until or slp
        for ex in (exl, exr):
            if blink:
                scr.rect(ex, ey + 2 * sc, 4 * sc, sc, (20, 10, 8))
            else:
                scr.rect(ex + sc, ey, 2 * sc, 4 * sc, FG)
                scr.rect(ex, ey + sc, 4 * sc, 2 * sc, FG)
                if mood == 2:  # heavy lids when worried
                    scr.rect(ex, ey, 4 * sc, sc, CORAL_D)
                px, py = int(round(self.pcur[0])), int(round(self.pcur[1]))
                scr.rect(ex + sc + px, ey + sc + py, 2 * sc - 1, 2 * sc, (25, 15, 12))
                scr.rect(ex + sc + px, ey + sc + py, sc // 2 + 1, sc // 2 + 1, (250, 250, 250))
        scr.rect(x + 3 * sc, y + 9 * sc, 2 * sc, sc, CHEEK)
        scr.rect(x + 15 * sc, y + 9 * sc, 2 * sc, sc, CHEEK)
        mx, my = x + 9 * sc, y + 9 * sc
        if mood == 0 and not blink:
            scr.rect(mx, my + sc, 2 * sc, sc, CORAL_D)
            scr.rect(mx - sc, my, sc, sc, CORAL_D)
            scr.rect(mx + 2 * sc, my, sc, sc, CORAL_D)
        elif mood == 1:
            scr.rect(mx - sc, my + sc, 4 * sc, sc, CORAL_D)
        else:
            scr.rect(mx, my + sc, 2 * sc, sc, CORAL_D)
            scr.rect(mx - sc, my + 2 * sc, sc, sc, CORAL_D)
            scr.rect(mx + 2 * sc, my + 2 * sc, sc, sc, CORAL_D)
            if (t * 2) % 2 < 1.4:
                dy = int(((t * 2) % 2) * 6)
                scr.rect(x + 21 * sc, y - sc + dy, sc, 2 * sc, CYAN)
        if slp:
            ph = (t * 0.7) % 1.0
            zx = x + 20 * sc + int(ph * 10)
            zy = y - int(ph * 22)
            scr.text(zx, zy, "Z", CYAN, 2)
            scr.text(zx + 14, zy + 12, "Z", (60, 130, 145), 1)
        if t < self.jump_until:
            scr.text(x + 8 * sc, y - 4 * sc, "!", ACCENT, 3)
        if self.bubble:
            self.draw_bubble(scr, x, y)


WATER = (20, 42, 72)
WATER_TOP = (30, 62, 102)
SAND = (116, 96, 66)
SAND_D = (88, 72, 52)
WEED = (52, 168, 96)
WEED_D = (36, 118, 68)
STARFISH = (255, 140, 80)
FRIEND_POSES = ["sleeping", "waving", "mindblown", "celebrating", "happy"]
# A session that is actually working right now looks like it. The pusher
# reports this per project, so the tank tells you what's running at a glance.
BUSY_POSES = ["working-thinking", "coding", "celebrating"]
IDLE_POSES = ["sleeping", "happy", "waving", "mindblown"]
PET_YOFF = {"sleeping": 8}  # lying poses sit down into the sand

# The aquarium panel, and the water inside it. draw_aquarium() insets by 4.
AQ_X, AQ_Y, AQ_W, AQ_H = 316, 352, 284, 108
AQ_IN_X0, AQ_IN_X1 = AQ_X + 4, AQ_X + AQ_W - 4      # 320 .. 596
FRIEND_FLOOR = 442
MAX_FRIENDS = 5

# Clawd gets out of the way as the tank fills: five friends plus a full-size
# crab do not fit in 276 pixels. Sprite cell size by friend count.
CLAWD_SCALE = {0: 5, 1: 4, 2: 4, 3: 3, 4: 3, 5: 3}


def friend_layout(n):
    """Evenly spaced centres across the water, plus the character budget for
    each sign so they don't collide at the tighter spacings."""
    if n <= 0:
        return [], 10
    x0, x1 = AQ_IN_X0 + 6, AQ_IN_X1 - 6
    pitch = (x1 - x0) / float(n)
    centres = [int(x0 + pitch * (i + 0.5)) for i in range(n)]
    # a sign is len(label) * 6 + 8 pixels wide, and must fit inside the pitch
    maxlen = max(3, min(12, int((pitch - 10) // 6)))
    return centres, maxlen


def clawd_bounds(sc):
    """How far Clawd can roam without pushing his claws through the glass.
    He is drawn from x - 8*sc to x + 28*sc."""
    lo = AQ_IN_X0 + 8 * sc + 2
    hi = AQ_IN_X1 - 28 * sc - 2
    if hi < lo:                       # absurdly large sprite; centre him
        lo = hi = (AQ_IN_X0 + AQ_IN_X1) // 2 - 10 * sc
    return float(lo), float(hi)


# Actions pushed in from outside the gamepad -- the desktop app's keyboard
# handler appends here and the run loop drains it. Empty and unused on the
# console, which reads /dev/input directly.
INJECTED = []

# What the bottom-right corner tells you to press. The desktop app overrides
# this, because it has no SELECT or START.
EXIT_HINT = "SELECT+START = EXIT"

VISITOR_GAP = (14.0, 26.0)      # seconds between visitors
_visitor_bag = []


def next_visitor_name():
    """Deal pets without replacement, so the whole roster gets seen rather
    than the same three showing up all evening."""
    global _visitor_bag
    if not _visitor_bag:
        _visitor_bag = [n for n in PETS if PETS.get(n)]
        random.shuffle(_visitor_bag)
    return _visitor_bag.pop() if _visitor_bag else None


class Visitor:
    """A pet drifting through the tank, captioned with its name.

    Most of the bundled pets are tied to a state you hope never happens -- the
    401 one wants your credentials to have expired -- so without this you would
    never meet them. Sessions still own the sea floor; visitors use the open
    water above it and are gone in a few seconds.

    Movement is a whole pixel per frame. This panel has one page of video
    memory and no vsync, so anything moving horizontally by fractions tears."""

    def __init__(self, name, y):
        self.name = name
        self.y = y
        self.phase = random.uniform(0, 6.28)
        # blit() clips to the screen, not to the panel, so a visitor half in
        # the tank would spill over the frame and into the trend chart next
        # door. Keep it entirely inside the water and let it appear from
        # behind the seaweed at the edges instead.
        frames = PETS.get(name) or []
        pw = frames[0][0] if frames else 40
        self.half = pw // 2 + 2
        self.x = float(AQ_IN_X0 + self.half)
        self.end = float(AQ_IN_X1 - self.half)

    def update(self):
        self.x += 1.0
        return self.x <= self.end

    def draw(self, scr):
        frames = PETS.get(self.name)
        if not frames:
            return
        t = time.time()
        pet = frames[int(t * 8 + self.phase) % len(frames)]
        pw, _ph, _runs = pet
        yy = int(self.y + math.sin(t * 1.5 + self.phase) * 2)
        x = int(self.x)
        label = self.name.upper().replace("-", " ")[:11]
        lw = scr.text_w(label, 1)
        lx = min(max(x - lw // 2, AQ_IN_X0 + 2), AQ_IN_X1 - lw - 2)
        scr.text(lx, yy - 9, label, (150, 214, 244), 1)
        scr.blit(x - pw // 2, yy, pet)


def parse_sessions(d):
    """[(name, terminal_count, busy)] from the payload.

    Prefers `session_info`, which carries per-project terminal counts and
    busy state. Falls back to the plain comma-separated `sessions` string so
    an older pusher still populates the tank."""
    if not d:
        return []
    info = d.get("session_info")
    out = []
    if isinstance(info, list):
        for item in info:
            if not isinstance(item, dict):
                continue
            name = str(item.get("n") or "").upper()[:10]
            if not name:
                continue
            try:
                count = max(1, int(item.get("c") or 1))
            except (TypeError, ValueError):
                count = 1
            out.append((name, count, 1 if item.get("b") else 0))
    if not out:
        sess = d.get("sessions") or ""
        if isinstance(sess, str):
            sess = [s for s in sess.split(",") if s]
        for s in sess:
            out.append((str(s).upper()[:10], 1, 0))
    return out[:MAX_FRIENDS]
TOSS_TIME = 0.85            # seconds a friend spends in the air
TOSS_HEIGHT = 54            # pixels at the top of the arc
TOSS_STAGGER = 0.22         # gap between one friend's launch and the next


class Friend:
    def __init__(self, name, x, floor, session="", count=1, busy=0, maxlen=8):
        self.session = session
        self.count = max(1, int(count))
        self.busy = 1 if busy else 0
        # "R36S X3" -- budget the suffix first, so the count is never the thing
        # that gets cut off, and the whole sign still fits its slot
        suffix = (" X%d" % self.count) if self.count > 1 else ""
        room = max(3, maxlen - len(suffix))
        self.label = session[:room] + suffix
        if name is None:
            # stable pose per session name, but drawn from the pool that
            # matches what the session is doing right now
            poses = BUSY_POSES if self.busy else IDLE_POSES
            pool = [p for p in poses if p in PETS]
            if not pool:
                pool = [p for p in FRIEND_POSES if p in PETS] or list(PETS)
            name = pool[sum(ord(c) for c in session) % len(pool)] if pool else ""
        self.name = name
        self.x = float(x)
        self.tx = float(x)
        self.floor = floor
        self.phase = random.uniform(0, 6.28)
        self.next_act = time.time() + random.uniform(8, 20)
        self.hop_until = 0
        self.next_hop = time.time() + random.uniform(4, 12)
        self.toss_at = 0.0        # when Clawd launches this one
        self.tossed = False       # pose already re-rolled at the apex?

    def draw_sign(self, scr, lower=0):
        if not self.session:
            return
        label = self.label or self.session[:8]
        w = len(label) * 6 + 8
        sx = int(self.x) - w // 2
        sy = self.floor + 1 + lower
        # algae-style sign: deep green board, bright kelp trim + leaf tips
        scr.rect(sx, sy, w, 11, (26, 78, 52))
        scr.frame(sx, sy, w, 11, (66, 178, 108), 1)
        scr.rect(sx + 2, sy - 3, 3, 3, (66, 178, 108))
        scr.rect(sx + w - 5, sy - 3, 3, 3, (52, 148, 90))
        scr.text(sx + 4, sy + 2, label, (200, 245, 215), 1)

    def update(self, xmin, xmax):
        t = time.time()
        if t > self.next_act:
            self.next_act = t + random.uniform(35, 70)
            if random.random() < 0.35:
                self.reroll()
        if t > self.next_hop:
            self.hop_until = t + 0.45
            self.next_hop = t + random.uniform(6, 16)
        # friends stay put: bob + hop only (sideways creep read as jitter)

    def pose_pool(self):
        poses = BUSY_POSES if self.busy else IDLE_POSES
        pool = [p for p in poses if p in PETS and p != self.name]
        return pool or [p for p in FRIEND_POSES if p in PETS and p != self.name]

    def reroll(self):
        pool = self.pose_pool()
        if pool:
            self.name = random.choice(pool)

    def shuffle(self):
        self.reroll()
        self.hop_until = time.time() + 0.45

    def toss(self, delay=0.0):
        """Get launched. Staggering the delay down the row makes it read as
        Clawd juggling them one after another rather than a synchronised jump."""
        self.toss_at = time.time() + delay
        self.tossed = False

    def toss_phase(self, t):
        """0..1 through the flight, or None when on the ground."""
        if not self.toss_at:
            return None
        k = (t - self.toss_at) / TOSS_TIME
        if k < 0 or k > 1:
            if k > 1:
                self.toss_at = 0.0
            return None
        return k

    def draw(self, scr):
        frames = PETS.get(self.name)
        if not frames:
            return
        t = time.time()
        lift = 0.0
        spin = 0.0
        k = self.toss_phase(t)
        if k is not None:
            lift = math.sin(k * math.pi) * TOSS_HEIGHT     # up and back down
            spin = 26                                      # flip through poses fast
            if not self.tossed and k > 0.45:
                # swap the pose at the apex: that's the showing-off part
                self.tossed = True
                pool = self.pose_pool()
                if pool:
                    self.name = random.choice(pool)
                    frames = PETS.get(self.name) or frames
        rate = 8 + spin
        pet = frames[int(t * rate + self.phase * 2) % len(frames)]
        w, h, _ = pet
        hop = 0
        if t < self.hop_until:
            hop = math.sin((self.hop_until - t) / 0.45 * math.pi) * 9
        yoff = PET_YOFF.get(self.name, 0)
        if k is not None:
            yoff = 0            # airborne: ignore the sit-into-the-sand offset
        scr.blit(int(self.x) - w // 2,
                 int(self.floor - h - hop - lift + yoff), pet)
        if k is not None and k < 0.35:
            # a couple of specks kicked up from the launch
            for i in range(3):
                sx = int(self.x) + (i - 1) * 6
                sy = int(self.floor - 2 - k * 26 - i * 3)
                scr.rect(sx, sy, 2, 2, (150, 220, 255))


def draw_aquarium(scr, x, y, w, h, t):
    panel(scr, x, y, w, h, "AQUARIUM")
    # water: light near surface, deeper below
    third = (h - 8) // 3
    scr.rect(x + 4, y + 4, w - 8, third, WATER_TOP)
    scr.rect(x + 4, y + 4 + third, w - 8, third,
             tuple((a + b) // 2 for a, b in zip(WATER_TOP, WATER)))
    scr.rect(x + 4, y + 4 + 2 * third, w - 8, h - 8 - 2 * third, WATER)
    # light rays from the surface
    for i in range(3):
        rx = x + 30 + i * (w // 3) + int(math.sin(t * 0.4 + i * 2) * 8)
        scr.rect(rx, y + 4, 3, third + 8, (44, 84, 128))
    # sand
    scr.rect(x + 4, y + h - 14, w - 8, 10, SAND)
    scr.rect(x + 4, y + h - 16, w - 8, 3, SAND_D)
    # shells
    scr.rect(x + 40, y + h - 12, 4, 3, (225, 218, 200))
    scr.rect(x + w - 60, y + h - 11, 3, 3, (250, 190, 160))
    # starfish
    sfx, sfy = x + w - 34, y + h - 22
    scr.rect(sfx + 3, sfy, 3, 9, STARFISH)
    scr.rect(sfx, sfy + 3, 9, 3, STARFISH)
    scr.rect(sfx + 1, sfy + 1, 2, 2, STARFISH)
    scr.rect(sfx + 6, sfy + 1, 2, 2, STARFISH)
    scr.rect(sfx + 1, sfy + 6, 2, 2, STARFISH)
    scr.rect(sfx + 6, sfy + 6, 2, 2, STARFISH)
    # seaweed
    for i, wx in enumerate((x + 26, x + w // 2 - 8, x + w - 38)):
        segs = 6 + (i % 2) * 2
        for sgi in range(segs):
            sy = y + h - 16 - sgi * 9
            if sy < y + 8:
                break
            off = math.sin(t * 1.4 + i * 2.1 + sgi * 0.55) * (2 + sgi * 0.5)
            col = WEED if sgi % 2 else WEED_D
            if sgi >= segs - 2:
                col = (72, 200, 120)  # bright tips
            scr.rect(int(wx + off), sy - 9, 5, 10, col)
    # bubbles
    for i in range(8):
        ph = (t * (0.10 + 0.02 * i) + i * 0.31) % 1.0
        bx = x + 16 + (i * 41) % (w - 34) + math.sin(t * 2 + i) * 3
        by = y + h - 18 - ph * (h - 34)
        s = 2 + (i % 3)
        scr.frame(int(bx), int(by), s + 2, s + 2, (120, 190, 220), 1)


def load_data():
    try:
        with open(DATA) as f:
            d = json.load(f)
        d["_age"] = time.time() - os.path.getmtime(DATA)
        d["_mtime"] = os.path.getmtime(DATA)
        return d
    except (OSError, ValueError):
        return None


def load_hist():
    pts = []
    try:
        with open(HIST) as f:
            for line in f:
                try:
                    r = json.loads(line)
                    pts.append((r["t"], r["fh"], r["sd"]))
                except (ValueError, KeyError):
                    pass
    except OSError:
        pass
    return pts[-120:]


def draw_meter(scr, x, y, w, label, sub, pct, shown, t):
    p = max(0, min(100, int(pct)))
    scr.text(x, y, label, DIM, 2)
    if sub:
        scr.text(x + scr.text_w(label + "  ", 2), y, "- " + sub, (95, 95, 110), 2)
    ptxt = "%d%%" % p
    scr.text(x + w - scr.text_w(ptxt, 3), y - 4, ptxt, FG, 3)
    by = y + 22
    bh = 24
    scr.rect(x, by, w, bh, TRACK)
    for ly in range(by + 3, by + bh, 6):
        scr.rect(x, ly, w, 1, (38, 38, 48))
    fill = int(w * max(0.0, min(100.0, shown)) / 100)
    col = pct_color(p)
    settled = abs(shown - p) < 1.5
    if fill > 8:
        # liquid: gentle constant slosh on the leading edge
        amp = 2.0
        bands = 8
        bandh = bh / bands
        for b in range(bands):
            off = math.sin(t * 1.8 + b * 0.85) * amp
            ex = int(max(6, min(w, fill + off)))
            scr.rect(x, int(by + b * bandh), ex, int(bandh + 1), col)
        scr.rect(x, by, max(6, fill - 4), 3, tuple(min(255, c + 45) for c in col))
        # bubbles drifting through the liquid
        if fill > 40:
            bc = tuple(min(255, c + 75) for c in col)
            for i in range(3):
                bx = int((t * (22 + 8 * i) + i * 131) % (fill - 16)) + 8
                byy = by + 5 + int((math.sin(t * 1.5 + i * 2.3) + 1)
                                   * 0.5 * (bh - 13))
                s = 3 + (i % 2)
                scr.frame(x + bx, byy, s, s, bc, 1)
        if settled:
            sweep = int((t * 55) % (w + 160)) - 80
            s0, s1 = max(0, sweep), min(fill - 6, sweep + 80)
            if s1 > s0:
                scr.rect(s0 + x, by + bh - 5, s1 - s0, 2,
                         tuple(min(255, c + 60) for c in col))
    elif fill > 0:
        scr.rect(x, by, fill, bh, col)
    for gx in (25, 50, 75):
        scr.rect(x + w * gx // 100, by + bh - 4, 1, 4, (90, 90, 105))


def draw_spark(scr, x, y, w, h, pts, window_s, now):
    # grid + labels
    for pct in (25, 50, 75):
        gy = y + h - 4 - pct * (h - 8) // 100
        scr.rect(x, gy, w - 26, 1, (44, 44, 56))
        scr.text(x + w - 24, gy - 3, "%d" % pct, (85, 85, 100), 1)
    # legend
    scr.rect(x + 2, y + 2, 8, 8, GOOD)
    scr.text(x + 13, y + 2, "5H", DIM, 1)
    scr.rect(x + 34, y + 2, 8, 8, WARN)
    scr.text(x + 45, y + 2, "7D", DIM, 1)
    # real time axis: window ends now, points sit at their timestamps
    t0 = now - window_s
    pts = [p for p in pts if p[0] >= t0]
    if len(pts) < 2:
        scr.text(x + 8, y + h // 2 - 4, "COLLECTING...", DIM, 2)
        return
    gw = w - 30
    base = y + h - 4
    span = h - 8

    def ypos(v):
        return base - max(0, min(100, v)) * span // 100

    def xpos(tt):
        return x + 2 + int(min(1.0, max(0.0, (tt - t0) / window_s)) * (gw - 2))

    # 5H as filled area between consecutive points
    for i in range(len(pts)):
        px = xpos(pts[i][0])
        nx = xpos(pts[i + 1][0]) if i + 1 < len(pts) else px + 2
        fy = ypos(pts[i][1])
        scr.rect(px, fy, max(2, nx - px), base - fy + 1, (36, 84, 56))
    # step-lines on top
    for idx, col in ((1, GOOD), (2, WARN)):
        prev = None
        for tt, fh, sd in pts:
            px = xpos(tt)
            py = ypos(fh if idx == 1 else sd)
            if prev is not None:
                scr.rect(prev[0], prev[1], max(2, px - prev[0] + 2), 2, col)
                y0, y1 = sorted((prev[1], py))
                scr.rect(px, y0, 2, max(2, y1 - y0 + 2), col)
            else:
                scr.rect(px, py, 2, 2, col)
            prev = (px, py)


def fancy_text(scr, x, y, line, scale, t):
    """Text with per-letter effects: ULTRATHINK = rainbow, ULTRACODE = purple."""
    mask = [None] * len(line)
    for kw, kind in (("ULTRATHINK", "r"), ("ULTRACODE", "p")):
        start = 0
        while True:
            i = line.find(kw, start)
            if i < 0:
                break
            for j in range(i, i + len(kw)):
                mask[j] = (kind, j - i)
            start = i + len(kw)
    cx = x
    for idx, ch in enumerate(line):
        m = mask[idx]
        if m is None:
            col = (45, 35, 30)
        elif m[0] == "r":
            r, g, b = colorsys.hsv_to_rgb((t * 0.9 + m[1] * 0.09) % 1.0, 0.85, 0.92)
            col = (int(r * 255), int(g * 255), int(b * 255))
        else:
            pulse = 0.55 + 0.45 * math.sin(t * 5 + m[1] * 0.55)
            col = (int(120 + 70 * pulse), int(40 + 30 * pulse), int(180 + 75 * pulse))
        scr.text(cx, y, ch, col, scale)
        cx += 6 * scale


SONG_COOLDOWN = 15  # between STARTS; stopping is always allowed
_last_song = [0.0]
_song_proc = [None]

# Players in order of preference. mpv handles everything; aplay is the most
# widely present fallback and copes with the .wav we ship.
PLAYERS = (
    ("mpv", ["--no-video", "--really-quiet"]),
    ("ffplay", ["-nodisp", "-autoexit", "-loglevel", "quiet"]),
    ("cvlc", ["--play-and-exit", "--intf", "dummy"]),
    ("paplay", []),
    ("aplay", ["-q"]),
)


def find_song():
    """anthem.* next to the script. Drop in any file with one of these
    extensions and it becomes the anthem."""
    for stem in ("anthem", "badchange"):
        for ext in ("ogg", "mp3", "wav", "m4a", "opus", "flac"):
            p = os.path.join(HERE, "%s.%s" % (stem, ext))
            if os.path.exists(p):
                return p
    return None


def play_song():
    """Anthem toggle. Returns 'ok', 'stopped', 'cooldown', 'missing'
    or 'noplayer'."""
    if SIM:
        # the desktop app runs in SIM mode but is a real thing someone is
        # looking at, so play it if the platform gives us a way
        song = find_song()
        if not song:
            return "missing"
        if os.name == "nt" and song.lower().endswith(".wav"):
            try:
                import winsound
                winsound.PlaySound(song, winsound.SND_FILENAME | winsound.SND_ASYNC)
                return "ok"
            except (ImportError, RuntimeError):
                return "noplayer"
        return "noplayer"
    proc = _song_proc[0]
    if proc is not None and proc.poll() is None:
        try:
            proc.terminate()
        except OSError:
            pass
        _song_proc[0] = None
        return "stopped"
    song = find_song()
    if not song:
        return "missing"
    now = time.time()
    if now - _last_song[0] < SONG_COOLDOWN:
        return "cooldown"
    for exe, args in PLAYERS:
        path = shutil.which(exe)
        if not path:
            continue
        if exe == "aplay" and not song.lower().endswith(".wav"):
            continue
        try:
            _song_proc[0] = subprocess.Popen(
                [path] + args + [song],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True)
        except OSError:
            continue
        _last_song[0] = now
        return "ok"
    return "noplayer"


def _cmdlines():
    """(pid, cmdline bytes) for every process we can read."""
    try:
        pids = os.listdir("/proc")
    except OSError:
        return
    for pid in pids:
        if not pid.isdigit():
            continue
        try:
            with open("/proc/%s/cmdline" % pid, "rb") as f:
                yield int(pid), f.read()
        except OSError:
            pass


NETD = os.path.join(HERE, "netd.py")


def ensure_netd():
    """Revive the network daemon if it died. EmulationStation kills the whole
    process group when a tool exits, silently, so this runs on a timer."""
    if SIM or not os.path.exists(NETD):
        return
    # Match the basename, not the full path: started from its own directory
    # the process's command line is just "python3 netd.py", and missing it
    # means starting a second one that dies on "address already in use".
    for _pid, cmd in _cmdlines():
        if b"netd.py" in cmd:
            return
    log = os.path.join(state_dir(), "netd.log")
    try:
        subprocess.Popen([sys.executable or "python3", NETD],
                         stdout=open(log, "ab"), stderr=subprocess.STDOUT,
                         start_new_session=True)
    except OSError:
        pass


def kill_siblings():
    """Two copies fighting over the framebuffer looks like a hardware glitch,
    so make sure we're the only one. Match the full path -- matching just
    'clawd.py' would also kill someone's editor."""
    if SIM:
        return
    me = os.getpid()
    marker = os.path.abspath(__file__).encode("utf-8", "replace")
    for pid, cmd in _cmdlines():
        if pid == me or marker not in cmd:
            continue
        try:
            os.kill(pid, 9)
        except (OSError, ProcessLookupError):
            pass


EV_FMT = "@llHHi"
# 24 bytes on a 64-bit userland, 16 on 32-bit ARM. The old code hardcoded 24,
# which decoded every button as garbage on 32-bit builds.
EV_SIZE = struct.calcsize(EV_FMT)

EV_KEY, EV_ABS = 1, 3


def _ior(type_ch, nr, size):
    return (2 << 30) | (size << 16) | (ord(type_ch) << 8) | nr


def EVIOCGABS(axis):
    return _ior("E", 0x40 + axis, 24)      # struct input_absinfo: 6 * __s32


def EVIOCGBIT(ev, size):
    return _ior("E", 0x20 + ev, size)


def _has_bit(buf, bit):
    idx = bit // 8
    return idx < len(buf) and bool(buf[idx] & (1 << (bit % 8)))


def open_inputs(path=None):
    path = path or CFG["input_dir"]
    devs = []
    try:
        names = sorted(os.listdir(path))
    except OSError:
        return []
    for n in names:
        if not n.startswith("event"):
            continue
        try:
            f = open(os.path.join(path, n), "rb", buffering=0)
            os.set_blocking(f.fileno(), False)
            devs.append(f)
        except OSError:
            pass
    return devs


def pick_stick(devs):
    """Left-stick calibration, taken from a device that really is a gamepad.

    Grabbing the first device that reports ABS_X picks up an accelerometer or
    a lid switch on some handhelds, which then drives the crab around."""
    fallback = None
    for f in devs:
        try:
            keys = bytearray(96)                       # KEY_MAX / 8 + 1
            try:
                fcntl.ioctl(f.fileno(), EVIOCGBIT(EV_KEY, len(keys)), keys)
                gamepad = any(_has_bit(keys, c)
                              for c in (304, 305, 307, 308, 314, 315, 704, 705))
            except OSError:
                gamepad = False
            buf = bytearray(24)
            fcntl.ioctl(f.fileno(), EVIOCGABS(ABS_X), buf)
            _v, amin, amax, _fuzz, flat, _res = struct.unpack_from("<iiiiii", buf, 0)
            if amax <= amin:
                continue
            info = (amin, amax, flat)
            if gamepad:
                return info
            if fallback is None:
                fallback = info
        except (OSError, struct.error):
            pass
    return fallback


def open_screen():
    """A normal 640x480 screen, or a device-sized plain one when the panel
    can't show the layout -- so we can at least say why."""
    try:
        return Screen(), None
    except PanelUnsupported as exc:
        if SIM:
            probe = Screen(logical=(W, H))     # just to read the faked geometry
            w, h, bpp = probe.dev_w, probe.dev_h, probe.dev_bpp
            if bpp != 32 or w < 200 or h < 120:
                return None, str(exc)
            return Screen(logical=(w, h), plain=True), str(exc)
        try:
            fb = open(FB, "r+b", buffering=0)
            w, h, bpp, _stride, _smem = probe_panel(fb.fileno())
            fb.close()
        except OSError:
            return None, str(exc)
        if bpp != 32 or w < 200 or h < 120:
            return None, str(exc)
        return Screen(logical=(w, h), plain=True), str(exc)


def wait_exit(scr, devs, buttons, draw, timeout=None):
    """Render `draw(scr)` at a lazy 12fps until SELECT+START. Used by the
    screens that aren't the dashboard."""
    held = set()
    started = time.time()
    left = int(os.environ.get("CLAWD_SIM_FRAMES", "8")) if SIM else -1
    while True:
        scr.clear()
        draw(scr)
        scr.flush()
        if SIM:
            left -= 1
            if left <= 0:
                return
        if timeout and time.time() - started > timeout:
            return
        for f in select.select(devs, [], [], 0.08)[0] if devs else []:
            for etype, code, value in read_events(f):
                if etype != EV_KEY:
                    continue
                act = buttons.action(code)
                if value:
                    held.add(act)
                else:
                    held.discard(act)
                if "select" in held and "start" in held:
                    return
        time.sleep(0.02)


def show_panel_problem(scr, msg, devs, buttons):
    lines = [
        ("POCKET CLAWD", 3, ACCENT),
        ("", 1, DIM),
        ("THIS SCREEN ISN'T SUPPORTED YET", 2, FG),
        (msg.upper(), 2, BAD),
        ("", 1, DIM),
        ("THE LAYOUT NEEDS A PANEL AT LEAST", 1, DIM),
        ("640X480 AND 32 BITS PER PIXEL.", 1, DIM),
        ("", 1, DIM),
        ("SEE DOCS/COMPATIBILITY.MD", 1, CHIP_FG),
        ("SELECT+START = EXIT", 1, CHIP_FG),
    ]

    def draw(s):
        total = sum(8 * sc + 6 for _txt, sc, _c in lines)
        y = max(4, (s.h - total) // 2)
        for txt, sc, col in lines:
            if txt:
                s.text((s.w - s.text_w(txt, sc)) // 2, y, txt, col, sc)
            y += 8 * sc + 6

    wait_exit(scr, devs, buttons, draw)


def map_buttons_wizard(devs, buttons):
    """Press each button in turn; write what we saw into config.json. This is
    the answer to handhelds whose codes don't match anything standard."""
    steps = [
        ("select", "SELECT"), ("start", "START"),
        ("talk", "THE A BUTTON"), ("shuffle", "THE B BUTTON"),
        ("dance", "THE X BUTTON"), ("wave", "THE Y BUTTON"),
        ("zoom_in", "L1"), ("zoom_out", "R1"), ("song", "L2"),
        ("up", "D-PAD UP"), ("down", "D-PAD DOWN"),
        ("left", "D-PAD LEFT"), ("right", "D-PAD RIGHT"),
    ]
    scr, problem = open_screen()
    if scr is None:
        print("cannot open the framebuffer: %s" % problem)
        return 1
    found = {}
    idx = [0]
    skip_at = [time.time() + 12]

    def draw(s):
        i = idx[0]
        s.text((s.w - s.text_w("BUTTON SETUP", 3)) // 2, 40, "BUTTON SETUP", ACCENT, 3)
        if i < len(steps):
            prompt = "PRESS " + steps[i][1]
            s.text((s.w - s.text_w(prompt, 3)) // 2, 150, prompt, FG, 3)
            left = max(0, int(skip_at[0] - time.time()))
            note = "OR WAIT %dS TO SKIP IT" % left
            s.text((s.w - s.text_w(note, 1)) // 2, 200, note, DIM, 1)
        else:
            s.text((s.w - s.text_w("ALL DONE!", 3)) // 2, 150, "ALL DONE!", GOOD, 3)
        s.text((s.w - s.text_w("STEP %d OF %d" % (min(i + 1, len(steps)), len(steps)), 1)) // 2,
               240, "STEP %d OF %d" % (min(i + 1, len(steps)), len(steps)), CHIP_FG, 1)
        done = ", ".join("%s=%d" % (k, v) for k, v in list(found.items())[-4:])
        if done:
            s.text((s.w - s.text_w(done, 1)) // 2, 300, done, DIM, 1)

    try:
        while idx[0] < len(steps):
            scr.clear()
            draw(scr)
            scr.flush()
            if time.time() > skip_at[0]:
                idx[0] += 1
                skip_at[0] = time.time() + 12
                continue
            for f in select.select(devs, [], [], 0.08)[0] if devs else []:
                for etype, code, value in read_events(f):
                    if etype == EV_KEY and value == 1 and code not in found.values():
                        found[steps[idx[0]][0]] = code
                        idx[0] += 1
                        skip_at[0] = time.time() + 12
                        break
            time.sleep(0.02)
        scr.clear()
        draw(scr)
        scr.flush()
        time.sleep(1.5)
    finally:
        scr.reset_pan()

    if not found:
        print("nothing recorded; config.json left alone")
        return 1
    path = os.path.join(HERE, "config.json")
    try:
        with open(path) as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        cfg = {}
    cfg.setdefault("buttons", {})
    for name, code in found.items():
        cfg["buttons"][name] = [code]
    with open(path, "w") as f:
        json.dump(cfg, f, indent=2, sort_keys=True)
        f.write("\n")
    print("wrote %d button(s) to %s" % (len(found), path))
    for name, code in sorted(found.items()):
        print("  %-9s %d" % (name, code))
    return 0


def read_events(f):
    """Yield (type, code, value) from one event device until it's drained."""
    while True:
        try:
            pkt = f.read(EV_SIZE)
        except (OSError, BlockingIOError):
            return
        if not pkt or len(pkt) < EV_SIZE:
            return
        _s, _us, etype, code, value = struct.unpack(EV_FMT, pkt)
        yield etype, code, value


def save_sim_output(frames, size):
    from PIL import Image
    imgs = [Image.frombytes("RGBA", size, fr, "raw", "BGRA").convert("RGB")
            for fr in frames]
    out = os.environ.get("CLAWD_SIM_OUT", "sim_out.gif")
    outdir = os.path.dirname(os.path.abspath(out))
    if outdir:
        os.makedirs(outdir, exist_ok=True)
    if out.lower().endswith(".png"):
        # a still, for the README -- and without GIF's 256-colour banding,
        # which was visibly chewing up the gradient background
        imgs[-1].save(out)
        print("sim still: %s" % out)
    else:
        imgs[0].save(out, save_all=True, append_images=imgs[1:],
                     duration=50, loop=0)
        print("sim gif: %s (%d frames)" % (out, len(imgs)))


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    buttons = ButtonMap(CFG.get("buttons"))

    if "--help" in argv or "-h" in argv:
        print(__doc__)
        print("Options:")
        print("  --map-buttons   press each button; writes codes to config.json")
        print("  --panel-info    report the detected panel and exit")
        print("Environment:")
        print("  CLAWD_CONFIG    path to config.json (default: next to this file)")
        print("  CLAWD_SIM=1     simulator mode; CLAWD_SIM_OUT=<file.gif|.png>")
        return 0

    if "--panel-info" in argv:
        try:
            fb = open(FB, "r+b", buffering=0)
        except OSError as exc:
            print("cannot open %s: %s" % (FB, exc))
            return 1
        w, h, bpp, stride, smem = probe_panel(fb.fileno())
        fb.close()
        print("panel      : %dx%d @ %d bpp" % (w, h, bpp))
        print("stride     : %d bytes  (%d would be tight-packed)" % (stride, w * 4))
        print("memory     : %s bytes" % (smem or "unknown"))
        print("event size : %d bytes" % EV_SIZE)
        if bpp != 32:
            print("verdict    : unsupported -- needs 32 bits per pixel")
        elif w < W or h < H:
            print("verdict    : unsupported -- smaller than 640x480")
        elif (w, h) == (W, H):
            print("verdict    : supported, pixel for pixel")
        else:
            print("verdict    : supported, letterboxed with a %d,%d margin"
                  % ((w - W) // 2, (h - H) // 2))
        return 0

    if "--map-buttons" in argv:
        if SIM:
            print("--map-buttons needs a real device")
            return 1
        return map_buttons_wizard(open_inputs(), buttons)

    kill_siblings()
    time.sleep(0.2)

    devs = [] if SIM else open_inputs()
    stick_cal = None if SIM else pick_stick(devs)

    scr, problem = open_screen()
    if scr is None:
        print("Pocket Clawd: %s" % problem)
        print("This panel can't show the 640x480 layout. See docs/COMPATIBILITY.md")
        return 1
    if problem:
        show_panel_problem(scr, problem, devs, buttons)
        scr.reset_pan()
        if SIM and scr.frames:
            save_sim_output(scr.frames, scr.frame_size)
        return 1
    if not SIM:
        print("panel: %s | event size: %d" % (scr.describe(), EV_SIZE), flush=True)
        if stick_cal:
            print("stick: min=%d max=%d flat=%d" % stick_cal, flush=True)

    held = set()
    last_input = time.time()
    clawd = Clawd(430, FRIEND_FLOOR + 6)
    if SIM and os.environ.get("CLAWD_SIM_SAY"):
        clawd.say(os.environ["CLAWD_SIM_SAY"])
        clawd.bubble = (clawd.bubble[0], time.time() + 999)
    friends = []  # populated live: one friend per active Claude Code session
    shown = {"fh": 0.0, "sd": 0.0, "fb": 0.0}
    try:
        run(scr, devs, held, last_input, clawd, friends, shown,
            0, [], 0.0, stick_cal, buttons)
    finally:
        scr.reset_pan()
    if SIM and scr.frames:
        save_sim_output(scr.frames, scr.frame_size)
    return 0


def run(scr, evs, held, last_input, clawd, friends, shown,
        last_mtime, hist, hist_at, stick_cal=None, buttons=None):
    buttons = buttons or ButtonMap()
    warn_at = clawd_config.as_int(CFG, "warn_pct", 60, 1, 100)
    crit_at = clawd_config.as_int(CFG, "crit_pct", 85, 1, 100)
    fps = clawd_config.as_int(CFG, "fps", 20, 5, 60)
    trend_steps = (5, 15, 30, 60, 120)  # x2min = 10/30/60/120/240 minutes
    # start at the 60-minute window: the widest one looks empty for the first
    # few hours after an install, which reads as broken rather than new
    trend_i = 2
    trend_n = trend_steps[trend_i]
    stick = [None]  # latest raw left-stick X value
    title_anim_start = time.time()
    next_title_anim = title_anim_start + 300
    sim_left = int(os.environ.get("CLAWD_SIM_FRAMES", "80")) if SIM else -1
    # 0 means run until something stops us -- what a live viewer wants. Decided
    # once, before the loop: deriving it from the counter each pass makes the
    # countdown turn into "forever" the moment it reaches zero.
    sim_forever = SIM and sim_left == 0
    visitor = [None]
    # the first one turns up quickly, so a fresh launch shows what this is
    next_visitor = [time.time() + 5.0]
    sim_action = os.environ.get("CLAWD_SIM_ACTION") if SIM else None
    # fire it a quarter of the way in, so there's a before and an after
    sim_action_at = int(sim_left * 0.75) if sim_left > 0 else -1
    netd_check = 0.0
    while True:
        if SIM and not sim_forever:
            if sim_left <= 0:
                return
            sim_left -= 1
        t = time.time()
        if t - netd_check > 60:
            ensure_netd()
            netd_check = t
        d = load_data()
        if d and d["_mtime"] != last_mtime:
            if last_mtime:
                clawd.poke()
            last_mtime = d["_mtime"]
            hist = load_hist()
        if t - hist_at > 30:
            hist = load_hist()
            hist_at = t
        fh = d.get("five_hour_pct", 0) if d else 0
        sd = d.get("seven_day_pct", 0) if d else 0
        # scoped_pct is the per-model weekly limit; fable_pct is the old name
        fb_ = (d.get("scoped_pct", d.get("fable_pct", 0)) or 0) if d else 0
        for k, v in (("fh", fh), ("sd", sd), ("fb", fb_)):
            shown[k] += (v - shown[k]) * 0.12
        worst = max(fh, sd, fb_)
        mood = 0 if worst < warn_at else (1 if worst < crit_at else 2)
        link = str((d or {}).get("link") or CFG.get("mode") or "LINK").upper()[:8]
        scoped = str((d or {}).get("scoped_label") or "SCOPED").upper()[:9]

        scr.clear(BG)
        if t > next_title_anim:
            title_anim_start = t
            next_title_anim = t + 300
        el = t - title_anim_start
        draw_title(scr, el if el < 3.0 else None)
        scr.text(W - 48 - scr.text_w("00:00", 2), 8, time.strftime("%H:%M"), CHIP_FG, 2)
        chip(scr, 48, 8, "LINK/" + link)
        scr.rect(48, 62, W - 96, 2, (60, 40, 34))

        panel(scr, 40, 84, 560, 74, "SYS/5H")
        panel(scr, 40, 170, 560, 74, "SYS/7D")
        panel(scr, 40, 256, 560, 74, "MDL/" + scoped)
        if d:
            draw_meter(scr, 60, 100, 520, "5-HOUR WINDOW",
                       "RESETS " + str(d.get("five_hour_reset", "?")), fh, shown["fh"], t)
            draw_meter(scr, 60, 186, 520, "WEEKLY / ALL",
                       "RESETS " + str(d.get("seven_day_reset", "?")), sd, shown["sd"], t)
            draw_meter(scr, 60, 272, 520, "WEEKLY / " + scoped, "", fb_, shown["fb"], t)
        else:
            scr.text(60, 110, "WAITING FOR USAGE DATA...", FG, 2)
            scr.text(60, 196, "START THE PUSHER ON YOUR PC,", DIM, 2)
            scr.text(60, 282, "OR SEE DOCS/NETWORKING.MD", DIM, 2)

        panel(scr, 40, 352, 260, 108, "TREND")
        draw_spark(scr, 46, 366, 248, 88, hist, trend_n * 120, t)
        ztxt = "%dMIN" % (trend_n * 2)
        scr.text(296 - scr.text_w(ztxt, 1) - 6, 358, ztxt, CHIP_FG, 1)
        draw_aquarium(scr, 316, 352, 284, 108, t)
        # one friend per active Claude Code project, sized and spaced to fit
        info = parse_sessions(d)
        if PETS and info != [(f.session, f.count, f.busy) for f in friends]:
            centres, maxlen = friend_layout(len(info))
            friends[:] = [
                Friend(None, centres[i], FRIEND_FLOOR, name, count, busy, maxlen)
                for i, (name, count, busy) in enumerate(info)]
            # Clawd steps back as the tank fills, and his roaming range with him
            clawd.sc = CLAWD_SCALE.get(len(info), 3)
            lo, hi = clawd_bounds(clawd.sc)
            clawd.x = min(max(clawd.x, lo), hi)
            clawd.tx = clawd.x
        clawd_lo, clawd_hi = clawd_bounds(clawd.sc)
        for fr in friends:
            fr.update(345, 575)
        # Tucked into the top-left of the water: with no friends Clawd is at
        # full size and owns the middle, so anything centred here sits behind
        # his shell.
        if not friends:
            scr.text(AQ_IN_X0 + 5, AQ_Y + 9, "NO SESSIONS", (70, 110, 140), 1)
        # anthropic rate-limited us: the 429 pet floats in to apologize
        if d and d.get("rl") and "429" in PETS:
            fr4 = PETS["429"]
            pet = fr4[int(t * 8) % len(fr4)]
            scr.blit(586 - pet[0] // 2,
                     int(388 - pet[1] // 2 + math.sin(t * 1.8) * 4), pet)
        clawd.ctx = d
        clawd.disconnected = d is None
        clawd.sleeping = d is not None and d["_age"] > 600
        # joystick drives the crab directly
        if stick[0] is not None:
            v = stick[0]
            dead = 0.30
            if stick_cal:
                amin, amax, flat = stick_cal
                center = (amin + amax) / 2.0
                half = (amax - amin) / 2.0
                norm = max(-1.0, min(1.0, (v - center) / half))
                # The driver's own `flat` is often far smaller than the real
                # resting noise (32 out of 1800 on this one, against measured
                # drift of ~170), so treat it as a lower bound, not the answer.
                if flat and half:
                    dead = max(0.25, min(0.5, flat / half))
            elif abs(v) > 512:
                norm = max(-1.0, min(1.0, v / 32768.0))
            else:
                norm = (v - 128) / 128.0
            if abs(norm) > dead:
                clawd.x = max(clawd_lo, min(clawd_hi, clawd.x + norm * 3.4))
                clawd.tx = clawd.x
                clawd.stick_until = t + 0.25
                last_input = t        # a real push counts as interaction
        clawd.update(clawd_lo, clawd_hi, t - last_input)
        clawd.draw(scr, mood)

        # a pet drifting through, so the whole roster gets seen and not just
        # whichever poses your live sessions happen to map to
        if visitor[0] is None:
            if t > next_visitor[0]:
                name = next_visitor_name()
                if name:
                    visitor[0] = Visitor(name, AQ_Y + 22)
                next_visitor[0] = t + random.uniform(*VISITOR_GAP)
        elif not visitor[0].update():
            visitor[0] = None
        if visitor[0] is not None:
            visitor[0].draw(scr)

        # The friends go in FRONT of Clawd. He is big and lives in the middle,
        # so drawing him last hid whichever session happened to be behind him --
        # and being able to see every session is the entire point of the tank.
        for fr in friends:
            if fr.name == "sleeping":
                fr.draw(scr)        # lying pose: sign in front, a bit lower
                fr.draw_sign(scr, 4)
            else:
                fr.draw_sign(scr)
                fr.draw(scr)

        status = "UPDATED " + str(d.get("updated", "?")) if d else "NO DATA"
        stale = d and d["_age"] > 150
        if stale:
            status += " (STALE!)"
        scr.text(48, 466, status, BAD if stale else DIM, 1)
        hint = EXIT_HINT
        scr.text(W - 48 - scr.text_w(hint, 1), 466, hint, DIM, 1)
        scr.flush()

        def fire(action):
            """One place where an action happens, whether it arrived as a
            button, a hat axis or an analog trigger."""
            if action is None:
                return
            clawd.on_action(action)
            if action == "shuffle":
                now = time.time()
                if friends:
                    # Clawd launches them one at a time, and each swaps pose at
                    # the top of its arc -- the showing-off is the point
                    clawd.throw_until = now + THROW_TIME + \
                        TOSS_STAGGER * max(0, len(friends) - 1)
                    for i, fr in enumerate(friends):
                        fr.toss(TOSS_STAGGER * i)
                    clawd.say(random.choice(
                        ("SHOWTIME!", "MEET THE CREW!", "UP YOU GO!", "TA-DA!")))
                else:
                    clawd.jump_until = now + 0.6
            elif action == "zoom_in":
                self_i[0] = max(0, self_i[0] - 1)
            elif action == "zoom_out":
                self_i[0] = min(len(trend_steps) - 1, self_i[0] + 1)
            elif action == "song":
                res = play_song()
                if res == "ok":
                    clawd.say("BAD CHANGE!")
                    clawd.dance_until = time.time() + 8.0
                elif res == "stopped":
                    clawd.dance_until = 0
                    clawd.say("OK OK. SILENCE.")
                elif res == "cooldown":
                    pass                      # quietly ignore mashing
                elif res == "noplayer":
                    clawd.say("NO AUDIO PLAYER HERE!")
                else:
                    clawd.say("NO SONG FILE YET!")

        self_i = [trend_i]
        # In the simulator there is no gamepad, so CLAWD_SIM_ACTION=shuffle
        # lets a preview show what a button actually does.
        if SIM and sim_action and sim_left == sim_action_at:
            fire(sim_action)
        while INJECTED:
            act = INJECTED.pop(0)
            if act == "quit":
                return
            last_input = time.time()
            fire(act)
        r = select.select(evs, [], [], 0.01)[0] if evs else []
        for f in r:
            for etype, code, value in read_events(f):
                if etype == EV_ABS:
                    if code == ABS_X:
                        # Deliberately NOT counted as user input here. These
                        # sticks emit a steady stream of small values at rest
                        # (measured: ~10 per second, drifting ~10% of range),
                        # and treating that as interaction means the idle
                        # timer never fires and Clawd never says anything on
                        # his own. Input is registered below, only if the
                        # stick actually moves past the deadzone.
                        stick[0] = value
                    elif code in (ABS_HAT0X, ABS_HAT0Y):
                        # d-pads that report as a hat rather than BTN_DPAD_*
                        last_input = time.time()
                        pair = ("left", "right") if code == ABS_HAT0X else ("up", "down")
                        for name in pair:
                            held.discard(name)
                        if value < 0:
                            held.add(pair[0])
                            fire(pair[0])
                        elif value > 0:
                            held.add(pair[1])
                            fire(pair[1])
                    elif code in (ABS_Z, ABS_RZ):
                        # analog triggers: treat a firm pull as a press
                        last_input = time.time()
                        name = "song" if code == ABS_Z else None
                        if name:
                            was = name in held
                            if value > 128 and not was:
                                held.add(name)
                                fire(name)
                            elif value <= 128:
                                held.discard(name)
                elif etype == EV_KEY:
                    last_input = time.time()
                    action = buttons.action(code)
                    if value == 1:
                        held.add(action or code)
                        fire(action)
                    elif value == 0:
                        held.discard(action or code)
                    if "select" in held and "start" in held:
                        return
        if self_i[0] != trend_i:
            trend_i = self_i[0]
            trend_n = trend_steps[trend_i]
        dt = time.time() - t
        if dt < 1.0 / fps:
            time.sleep(1.0 / fps - dt)


if __name__ == "__main__":
    sys.exit(main())
