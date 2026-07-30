#!/usr/bin/env python3
"""Render Pocket Clawd on a PC, with no handheld attached.

The widget's drawing code is pure Python writing into a byte buffer, so the
only thing the device provides is somewhere to send that buffer. In simulator
mode it goes to a GIF or a PNG instead of /dev/fb0, which makes it possible to
iterate on the layout -- and to take the README screenshots -- without a cable.

    python tools/sim.py                       # preview.gif of the normal state
    python tools/sim.py --state critical      # a different state
    python tools/sim.py --all --out-dir docs/screenshots
    python tools/sim.py --panel 1280x720      # check the letterboxing

Fixture session names are deliberately generic; they show up on screen and
these images end up in a public README.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEVICE = os.path.join(ROOT, "device")
SIMDIR = os.path.join(ROOT, "sim")

# five_hour, seven_day, scoped, rate-limited, sessions, age of the data
STATES = {
    "normal":      (32, 41, 28, 0, ["SIDEQUEST"], 5),
    "busy":        (68, 74, 61, 0, ["SIDEQUEST", "PORTFOLIO"], 5),
    "critical":    (94, 88, 91, 0, ["SIDEQUEST", "PORTFOLIO", "DOTFILES"], 5),
    "ratelimited": (88, 79, 84, 1, ["SIDEQUEST"], 5),
    "idle":        (21, 37, 15, 0, [], 5),
    "sleeping":    (44, 52, 30, 0, ["SIDEQUEST"], 900),
    "stale":       (44, 52, 30, 0, ["SIDEQUEST"], 200),
    "nodata":      None,
}


def write_fixtures(state, simdir):
    if os.path.isdir(simdir):
        shutil.rmtree(simdir, ignore_errors=True)
    os.makedirs(simdir, exist_ok=True)
    spec = STATES[state]
    if spec is None:                       # the "no data yet" screen
        return
    fh, sd, scoped, rl, sessions, age = spec
    now = time.time()
    payload = {
        "five_hour_pct": fh,
        "five_hour_reset": time.strftime("%H:%M", time.localtime(now + 7200)),
        "seven_day_pct": sd,
        "seven_day_reset": "THU 13:00",
        "scoped_pct": scoped,
        "scoped_label": "OPUS",
        "updated": time.strftime("%H:%M", time.localtime(now - age)),
        "epoch": int(now - age),
        "note": "LAST PROJECT: SIDEQUEST",
        "sessions": ",".join(sessions),
        "rl": rl,
        "link": "wifi",
    }
    data = os.path.join(simdir, "sim_usage.json")
    with open(data, "w") as f:
        json.dump(payload, f)
    # the widget derives freshness from the file's mtime, not the payload
    os.utime(data, (now - age, now - age))

    # a plausible couple of hours of history for the trend panel
    with open(os.path.join(simdir, "sim_hist.jsonl"), "w") as f:
        n = 60
        for i in range(n):
            t = now - (n - i) * 120
            k = i / float(n - 1)
            rec = {
                "t": int(t),
                "fh": int(max(0, fh * (0.35 + 0.65 * k) + (i % 5) - 2)),
                "sd": int(max(0, sd * (0.80 + 0.20 * k))),
                "fb": int(max(0, scoped * (0.5 + 0.5 * k))),
            }
            if rl and i > n - 4:
                rec["rl"] = 1
            f.write(json.dumps(rec, separators=(",", ":")) + "\n")


def render(state, out, frames, say=None, panel=None):
    simdir = os.path.join(SIMDIR, state)
    write_fixtures(state, simdir)
    env = dict(os.environ)
    env["CLAWD_SIM"] = "1"
    env["CLAWD_SIM_DIR"] = simdir
    env["CLAWD_SIM_FRAMES"] = str(frames)
    env["CLAWD_SIM_OUT"] = out
    if say:
        env["CLAWD_SIM_SAY"] = say
    if panel:
        env["CLAWD_SIM_PANEL"] = panel
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    r = subprocess.run([sys.executable, os.path.join(DEVICE, "clawd.py")],
                       env=env, cwd=ROOT)
    return r.returncode


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--state", default="normal", choices=sorted(STATES),
                    help="which situation to fake (default: normal)")
    ap.add_argument("--all", action="store_true",
                    help="render a still for every state")
    ap.add_argument("--out", help="output file; .gif animates, .png is a still")
    ap.add_argument("--out-dir", default=SIMDIR, help="where --all writes")
    ap.add_argument("--frames", type=int, default=80)
    ap.add_argument("--say", help="force a speech bubble")
    ap.add_argument("--panel", help="pretend the panel is this size, e.g. 1280x720")
    args = ap.parse_args()

    if args.all:
        os.makedirs(args.out_dir, exist_ok=True)
        bad = 0
        for state in sorted(STATES):
            out = os.path.join(args.out_dir, "%s.png" % state)
            print("--- %s" % state)
            bad |= render(state, out, max(30, args.frames), args.say, args.panel)
        return bad

    out = args.out or os.path.join(SIMDIR, "preview.gif")
    return render(args.state, out, args.frames, args.say, args.panel)


if __name__ == "__main__":
    sys.exit(main())
