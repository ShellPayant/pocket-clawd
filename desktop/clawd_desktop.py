#!/usr/bin/env python3
"""Pocket Clawd on your desktop. No handheld required.

    python desktop/clawd_desktop.py
    python desktop/clawd_desktop.py --scale 2      # double size
    python desktop/clawd_desktop.py --demo         # fake data, no login needed

The same display code that runs on the console, in a window. It reads your
Claude usage itself, so there's no console, no network setup and nothing to
push -- it's the whole thing in one process.

Keys
    A          Clawd says something          Left / Right   his moods
    B          toss the friends              Up / Down
    X  Y       dance / wave                  [  ]           zoom the chart
    M          play the anthem               Esc            quit

Needs Pillow (for the window's image) and Claude Code logged in. Everything
else is standard library.
"""
import argparse
import json
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# The display is the console's, run in its simulator mode: same layout, same
# crab, same everything, just drawing into memory instead of /dev/fb0.
STATE = os.path.join(
    os.environ.get("APPDATA") or os.path.expanduser("~/.local/share"),
    "pocket-clawd-desktop")
os.makedirs(STATE, exist_ok=True)
os.environ["CLAWD_SIM"] = "1"
os.environ["CLAWD_SIM_DIR"] = STATE
os.environ.setdefault("CLAWD_SIM_FRAMES", "0")     # 0 = run until closed

sys.path.insert(0, os.path.join(ROOT, "device"))
sys.path.insert(0, os.path.join(ROOT, "pc"))
import clawd                     # noqa: E402
import clawd_pusher as pusher    # noqa: E402

KEYS = {
    "a": "talk", "b": "shuffle", "x": "dance", "y": "wave",
    "m": "song", "bracketleft": "zoom_out", "bracketright": "zoom_in",
    "Left": "left", "Right": "right", "Up": "up", "Down": "down",
}

DEMO = {
    "five_hour_pct": 63, "five_hour_reset": "21:20",
    "seven_day_pct": 41, "seven_day_reset": "THU 13:00",
    "scoped_pct": 55, "scoped_label": "OPUS",
    "note": "LAST PROJECT: SIDEQUEST", "sessions": "SIDEQUEST,PORTFOLIO",
    "session_info": [{"n": "SIDEQUEST", "c": 3, "b": 1},
                     {"n": "PORTFOLIO", "c": 1, "b": 0}],
    "rl": 0, "link": "desktop",
}


def write_usage(payload):
    """Drop the numbers where the display expects to find them, and append to
    the history the trend chart is drawn from -- same file format the console
    uses, so the two are interchangeable."""
    payload = dict(payload)
    payload["updated"] = time.strftime("%H:%M")
    payload["epoch"] = int(time.time())
    payload.setdefault("link", "desktop")
    with open(os.path.join(STATE, "sim_usage.json"), "w") as f:
        json.dump(payload, f)

    key = (int(payload.get("five_hour_pct") or 0),
           int(payload.get("seven_day_pct") or 0),
           int(payload.get("scoped_pct") or 0))
    hist = os.path.join(STATE, "sim_hist.jsonl")
    last = None
    try:
        with open(hist) as f:
            for line in f:
                last = line
    except OSError:
        pass
    if last:
        try:
            prev = json.loads(last)
            if (prev["fh"], prev["sd"], prev["fb"]) == key and \
                    time.time() - prev["t"] < 120:
                return                       # unchanged and recent; skip
        except (ValueError, KeyError):
            pass
    with open(hist, "a") as f:
        f.write(json.dumps({"t": int(time.time()), "fh": key[0],
                            "sd": key[1], "fb": key[2]},
                           separators=(",", ":")) + "\n")


class Feed(threading.Thread):
    """Asks Anthropic for your usage on a timer. Same code the pusher uses, so
    there is exactly one implementation of this to get wrong."""

    daemon = True

    def __init__(self, interval=120, demo=False, log=print):
        threading.Thread.__init__(self)
        self.interval = max(60, interval)
        self.demo = demo
        self.log = log
        self.stop = threading.Event()

    def run(self):
        if self.demo:
            write_usage(DEMO)
            return
        token = pusher.read_token()
        if not token:
            self.log("No Claude Code login found. Run with --demo to see it "
                     "working with made-up numbers.")
            return
        backoff = 0
        while not self.stop.is_set():
            try:
                payload = pusher.build_payload(pusher.fetch_usage(token))
                write_usage(payload)
                self.log("usage: 5h %d%%  7d %d%%  %s %d%%"
                         % (payload["five_hour_pct"], payload["seven_day_pct"],
                            payload["scoped_label"], payload["scoped_pct"]))
                backoff = 0
                wait = self.interval
            except Exception as exc:           # noqa: BLE001 - keep the app up
                msg = str(exc)
                if "429" in msg:
                    backoff = 300
                    self.log("rate limited; retrying in 5 minutes")
                elif "401" in msg or "403" in msg:
                    backoff = 300
                    self.log("login rejected - sign in with Claude Code again")
                else:
                    backoff = 60
                    self.log("could not fetch usage: %s" % msg)
                wait = backoff
            self.stop.wait(wait)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scale", type=int, default=1, choices=(1, 2, 3),
                    help="window size multiplier")
    ap.add_argument("--demo", action="store_true",
                    help="made-up numbers; no Claude Code login needed")
    ap.add_argument("--interval", type=int, default=120,
                    help="seconds between checks (minimum 60)")
    args = ap.parse_args()

    try:
        import tkinter as tk
    except ImportError:
        print("tkinter isn't available in this Python build.")
        print("On Debian/Ubuntu: sudo apt install python3-tk")
        return 1
    try:
        from PIL import Image, ImageTk
    except ImportError:
        print("Pillow is needed for the window: pip install pillow")
        return 1

    clawd.EXIT_HINT = "ESC = QUIT"

    root = tk.Tk()
    root.title("Pocket Clawd")
    root.resizable(False, False)
    W, H = clawd.W, clawd.H
    canvas = tk.Canvas(root, width=W * args.scale, height=H * args.scale,
                       highlightthickness=0, bg="#0c0d16")
    canvas.pack()
    item = canvas.create_image(0, 0, anchor="nw")
    status = tk.Label(root, text="starting...", anchor="w", padx=8,
                      font=("Segoe UI", 9))
    status.pack(fill="x")

    latest = {"frame": None, "size": (W, H)}
    lock = threading.Lock()

    def on_frame(buf, size):
        with lock:
            latest["frame"] = buf
            latest["size"] = size

    def say(msg):
        root.after(0, lambda: status.config(text=msg))

    # --- the display, driven in a worker thread ---------------------------
    def render():
        scr = clawd.Screen()
        scr.on_frame = on_frame
        pet = clawd.Clawd(430, clawd.FRIEND_FLOOR + 6)
        try:
            clawd.run(scr, [], set(), time.time(), pet, [],
                      {"fh": 0.0, "sd": 0.0, "fb": 0.0}, 0, [], 0.0, None,
                      clawd.ButtonMap())
        except Exception as exc:               # noqa: BLE001
            say("display stopped: %s" % exc)

    threading.Thread(target=render, daemon=True).start()
    feed = Feed(args.interval, args.demo, say)
    feed.start()
    say("demo data" if args.demo else "reading your Claude usage...")

    # --- keyboard ---------------------------------------------------------
    def on_key(event):
        if event.keysym == "Escape":
            quit_app()
            return
        action = KEYS.get(event.keysym) or KEYS.get(event.keysym.lower())
        if action:
            clawd.INJECTED.append(action)

    def quit_app():
        clawd.INJECTED.append("quit")
        feed.stop.set()
        root.after(120, root.destroy)

    root.bind("<Key>", on_key)
    root.protocol("WM_DELETE_WINDOW", quit_app)

    # --- pump frames into the window --------------------------------------
    keep = {}

    def tick():
        with lock:
            buf, size = latest["frame"], latest["size"]
        if buf:
            img = Image.frombytes("RGBA", size, buf, "raw", "BGRA").convert("RGB")
            if args.scale != 1:
                img = img.resize((size[0] * args.scale, size[1] * args.scale),
                                 Image.NEAREST)
            keep["photo"] = ImageTk.PhotoImage(img)   # or Tk garbage-collects it
            canvas.itemconfig(item, image=keep["photo"])
        root.after(50, tick)

    tick()
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
