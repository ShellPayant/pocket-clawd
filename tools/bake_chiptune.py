#!/usr/bin/env python3
"""Synthesise the default anthem: an original chiptune, built from arithmetic.

L2 plays an audio file. The obvious thing to ship is a song you like, which is
the one thing a public repo can't do -- so this writes one instead. Square and
triangle waves, noise percussion, no samples and no dependencies, which makes it
unambiguously ours to give away.

    python tools/bake_chiptune.py              # device/anthem.wav
    python tools/bake_chiptune.py --bpm 150
    python tools/bake_chiptune.py --loops 3    # longer

Want a different one? Drop any file named anthem.mp3 / .ogg / .wav into the app
folder and it takes over -- see the README.
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

# note -> Hz, two octaves of A minor. Written as names so the tune below is
# readable as music rather than as a list of frequencies.
BASE = {"A": 220.00, "B": 246.94, "C": 261.63, "D": 293.66,
        "E": 329.63, "F": 349.23, "G": 392.00}


def hz(note):
    """'A4' -> 440.0, 'C5' -> 523.25, '-' -> rest."""
    if note in ("-", None):
        return None
    letter, octave = note[0], int(note[1])
    f = BASE[letter] * (2 ** (octave - 3))
    if len(note) > 2 and note[2] == "#":
        f *= 2 ** (1 / 12.0)
    return f


# (notes, beats each) -- eighth notes at the given bpm
HOOK = ["A4", "-", "C5", "E5", "D5", "C5", "A4", "-",
        "A4", "C5", "E5", "G5", "A5", "-", "E5", "D5"]
VERSE = ["C5", "E5", "D5", "C5", "A4", "-", "G4", "A4",
         "C5", "-", "A4", "G4", "E4", "-", "-", "-"]
LIFT = ["E5", "G5", "A5", "G5", "E5", "D5", "C5", "D5",
        "E5", "G5", "A5", "C6", "B5", "A5", "G5", "E5"]

BASS_A = ["A2", "-", "A3", "-", "G2", "-", "G3", "-"]
BASS_B = ["F2", "-", "F3", "-", "E2", "-", "E3", "-"]
BASS_C = ["C3", "-", "C3", "G2", "D3", "-", "D3", "A2"]

ARP_AM = ["A4", "C5", "E5", "C5"]
ARP_G = ["G4", "B4", "D5", "B4"]
ARP_F = ["F4", "A4", "C5", "A4"]
ARP_C = ["C5", "E5", "G5", "E5"]


def envelope(i, n, attack=0.008, release=0.30):
    a = max(1, int(n * attack))
    r = max(1, int(n * release))
    if i < a:
        return i / a
    if i > n - r:
        return max(0.0, (n - i) / r)
    return 1.0


def square(freq, n, duty=0.5, vol=0.5, vibrato=0.0):
    """A pulse wave. Duty changes the character completely: 0.5 is hollow and
    flutey, 0.25 is nasal and cuts through, 0.125 is thin and reedy."""
    out = [0.0] * n
    if not freq:
        return out
    phase = 0.0
    for i in range(n):
        f = freq
        if vibrato:
            f *= 1.0 + vibrato * math.sin(2 * math.pi * 5.5 * i / RATE)
        phase += f / RATE
        out[i] = (1.0 if (phase % 1.0) < duty else -1.0) * vol * envelope(i, n)
    return out


def triangle(freq, n, vol=0.5):
    """Softer than a square -- the bass, so it doesn't fight the lead."""
    out = [0.0] * n
    if not freq:
        return out
    for i in range(n):
        p = (i * freq / RATE) % 1.0
        out[i] = (4 * abs(p - 0.5) - 1) * vol * envelope(i, n, release=0.15)
    return out


def noise(n, vol=0.25, decay=14.0, tone=1.0):
    rnd = random.Random(11)          # fixed seed: the file is reproducible
    out, last = [0.0] * n, 0.0
    for i in range(n):
        v = rnd.random() * 2 - 1
        last = last + (v - last) * tone      # low-pass -> kick vs hat
        out[i] = last * vol * math.exp(-decay * i / n)
    return out


def render(bpm, loops):
    beat = 60.0 / bpm / 2                    # eighth note
    step = int(beat * RATE)

    # arrangement: intro on the hook, verse, hook, lift, hook
    lead = HOOK + VERSE + HOOK + LIFT + HOOK
    lead = lead * max(1, loops)
    total = len(lead) * step + RATE // 2
    buf = [0.0] * total

    def lay(samples, at):
        for i, s in enumerate(samples):
            j = at + i
            if j < total:
                buf[j] += s

    # lead, doubled a hair late and quieter for width
    for k, note in enumerate(lead):
        f = hz(note)
        if f:
            lay(square(f, int(step * 1.7), 0.5, 0.30, vibrato=0.004), k * step)
            lay(square(f, int(step * 1.6), 0.25, 0.10), k * step + int(0.011 * RATE))

    # bass, two bars per pattern
    bass = (BASS_A + BASS_B + BASS_A + BASS_C) * (len(lead) // 32 + 1)
    for k, note in enumerate(bass[:len(lead)]):
        f = hz(note)
        if f:
            lay(triangle(f, int(step * 1.9), 0.34), k * step)

    # arpeggio underneath, one chord per bar
    chords = [ARP_AM, ARP_G, ARP_F, ARP_C]
    for bar in range(len(lead) // 8 + 1):
        arp = chords[bar % len(chords)]
        for k in range(8):
            f = hz(arp[k % len(arp)])
            at = (bar * 8 + k) * step
            if at < total and f:
                lay(square(f * 2, int(step * 0.8), 0.125, 0.075), at)

    # drums: kick on 1 and 3, snare on 2 and 4, hats on eighths
    for k in range(len(lead)):
        at = k * step
        if k % 8 in (0, 3):
            lay(noise(step, 0.30, 26.0, tone=0.06), at)          # kick
        if k % 8 in (4,):
            lay(noise(step // 2, 0.22, 16.0, tone=0.5), at)      # snare
        if k % 2 == 1:
            lay(noise(step // 5, 0.06, 30.0, tone=1.0), at)      # hat

    peak = max(0.0001, max(abs(s) for s in buf))
    gain = 0.86 / peak
    return [int(max(-32767, min(32767, s * gain * 32767))) for s in buf]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bpm", type=int, default=136)
    ap.add_argument("--loops", type=int, default=1)
    ap.add_argument("--out", default=os.path.join(ROOT, "device", "anthem.wav"))
    args = ap.parse_args()

    samples = render(args.bpm, args.loops)
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
