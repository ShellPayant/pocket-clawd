#!/usr/bin/env python3
"""Synthesise the anthem: an original chiptune, built from arithmetic.

L2 plays an audio file. The obvious thing to ship is a song you like, which is
the one thing a public repo can't do -- so this writes one instead. Square-wave
lead, pulse bass, noise percussion, no samples and no dependencies, which makes
it unambiguously ours to give away.

    python tools/bake_chiptune.py            # device/anthem.wav
    python tools/bake_chiptune.py --bpm 150

Drop any .ogg/.mp3/.wav named anthem.* into the app folder to replace it.
"""
import argparse
import math
import os
import random
import struct
import sys
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RATE = 22050

# A minor pentatonic, which is hard to make sound wrong.
A3, C4, D4, E4, G4, A4, C5, D5, E5, G5, A5 = (
    220.00, 261.63, 293.66, 329.63, 392.00, 440.00,
    523.25, 587.33, 659.25, 783.99, 880.00)

# (frequency, beats). None is a rest.
LEAD = [
    (A4, 1), (C5, 1), (E5, 1), (D5, 1),
    (C5, 1), (A4, 1), (G4, 2),
    (A4, 1), (C5, 1), (E5, 1), (G5, 1),
    (A5, 2), (E5, 1), (D5, 1),
    (C5, 1), (E5, 1), (D5, 1), (C5, 1),
    (A4, 2), (None, 1), (G4, 1),
    (A4, 1), (E4, 1), (A4, 1), (C5, 1),
    (A4, 4),
]
BASS = [
    (A3, 2), (A3, 2), (G4 / 2, 2), (G4 / 2, 2),
    (A3, 2), (A3, 2), (C4, 2), (E4, 2),
    (A3, 2), (A3, 2), (G4 / 2, 2), (G4 / 2, 2),
    (D4, 2), (D4, 2), (A3, 4),
]


def envelope(i, n, attack=0.01, release=0.25):
    """Quick attack, slow release -- the classic plucked chip sound."""
    a = max(1, int(n * attack))
    r = max(1, int(n * release))
    if i < a:
        return i / a
    if i > n - r:
        return max(0.0, (n - i) / r)
    return 1.0


def square(freq, n, duty=0.5, vol=0.5):
    out = [0.0] * n
    if not freq:
        return out
    period = RATE / freq
    for i in range(n):
        phase = (i % period) / period
        s = 1.0 if phase < duty else -1.0
        out[i] = s * vol * envelope(i, n)
    return out


def noise(n, vol=0.25, decay=12.0):
    rnd = random.Random(7)          # fixed seed: the file is reproducible
    return [(rnd.random() * 2 - 1) * vol * math.exp(-decay * i / n)
            for i in range(n)]


def render(bpm):
    beat = 60.0 / bpm / 2            # eighth notes
    total = int(sum(b for _f, b in LEAD) * beat * RATE) + RATE // 2
    buf = [0.0] * total

    def lay(track, duty, vol, offset=0):
        pos = offset
        for freq, beats in track:
            n = int(beats * beat * RATE)
            if freq:
                for i, s in enumerate(square(freq, n, duty, vol)):
                    if pos + i < total:
                        buf[pos + i] += s
            pos += n

    lay(LEAD, 0.5, 0.34)
    lay(LEAD, 0.5, 0.12, int(0.012 * RATE))   # slight detune-by-delay, fatter
    lay(BASS, 0.25, 0.30)

    # percussion on every beat, with a louder hit on the downbeat
    step = int(beat * RATE)
    for k in range(0, total - step, step):
        hit = noise(step // 3, 0.22 if (k // step) % 4 == 0 else 0.10)
        for i, s in enumerate(hit):
            if k + i < total:
                buf[k + i] += s

    peak = max(0.0001, max(abs(s) for s in buf))
    gain = 0.85 / peak
    return [int(max(-32767, min(32767, s * gain * 32767))) for s in buf]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bpm", type=int, default=132)
    ap.add_argument("--out", default=os.path.join(ROOT, "device", "anthem.wav"))
    args = ap.parse_args()

    samples = render(args.bpm)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with wave.open(args.out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(struct.pack("<%dh" % len(samples), *samples))
    print("wrote %s (%.1fs, %d KB)" % (args.out, len(samples) / float(RATE),
                                       os.path.getsize(args.out) // 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
