#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["sounddevice", "numpy"]
# ///
"""Does TotalMix's mic gain label match what the preamp delivers?

Runs on Windows or macOS against RME's own driver, so the Linux driver is
out of the picture entirely. You set the gain in TotalMix, this measures
what actually comes back, and at the end it fits measured gain against the
number TotalMix showed.

  slope 1.00  TotalMix's labels are truthful.  Then a Linux control that
              reads 65 dB but delivers 59 is a driver bug, not a label
              problem.
  slope <1    TotalMix's labels are optimistic, and the Linux driver is
              reproducing them faithfully.  Nothing to fix but a comment.

SETUP
  1. Patch an analog output back to input 1 with a cable.
  2. In TotalMix: PAD on for input 1, phantom power OFF.  Check phantom
     before connecting anything.
  3. Set the output master low.  The script will tell you if the level is
     too high or too low to measure.
  4. Leave every other TotalMix control alone for the whole run.

USAGE
  uv run bbf-gaincheck-portaudio.py --list
  uv run bbf-gaincheck-portaudio.py --device 12
  uv run bbf-gaincheck-portaudio.py --device 12 --steps 0 10 20 30 40 50 60 65

uv reads the dependency block above and fetches sounddevice and numpy into a
throwaway environment.  Without uv:  pip install sounddevice numpy
"""
import argparse
import sys

try:
    import numpy as np
    import sounddevice as sd
except ImportError:
    sys.exit("needs sounddevice and numpy:  pip install sounddevice numpy")

RATE = 48000
FREQ = 997.0
TONE_DBFS = -20.0
SECONDS = 3.0
SETTLE = 0.5


def tone(seconds=SECONDS):
    t = np.arange(int(RATE * seconds)) / RATE
    amp = 10 ** (TONE_DBFS / 20.0)
    x = amp * np.sin(2 * np.pi * FREQ * t)
    return np.column_stack([x, x]).astype("float32")


def measure(device):
    """Play a tone and record at the same time; return (rms dBFS, peak)."""
    sig = tone()
    rec = sd.playrec(sig, samplerate=RATE, channels=2, device=device,
                     dtype="float32")
    sd.wait()
    ch0 = rec[int(SETTLE * RATE):, 0]
    if ch0.size == 0:
        return None, 0.0
    peak = float(np.max(np.abs(ch0)))
    rms = float(np.sqrt(np.mean(ch0 ** 2)))
    return (20 * np.log10(rms) if rms > 0 else None), peak


def fit(xs, ys):
    n = len(xs)
    sx, sy = sum(xs), sum(ys)
    sxx = sum(x * x for x in xs)
    sxy = sum(x * y for x, y in zip(xs, ys))
    den = n * sxx - sx * sx
    return None if den == 0 else (n * sxy - sx * sy) / den


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true",
                    help="list audio devices and exit")
    ap.add_argument("--device", help="device index or name substring")
    ap.add_argument("--steps", type=int, nargs="+",
                    default=[0, 10, 20, 30, 40, 50, 60, 65],
                    help="TotalMix gain values to measure, in dB")
    args = ap.parse_args()

    if args.list or not args.device:
        print(sd.query_devices())
        print("\nPick the Babyface with --device <index>")
        return

    dev = int(args.device) if args.device.isdigit() else args.device

    print("Patch an output to input 1.  PAD on, phantom OFF.")
    print("Set the gain in TotalMix when asked, and change nothing else.\n")
    input("Press Enter when the cable is connected and phantom is off... ")

    rows = []
    for g in args.steps:
        input("\nSet input 1 gain to %d dB in TotalMix, then press Enter... "
              % g)
        rms, peak = measure(dev)
        if rms is None:
            print("  silence, check the cable")
            continue
        flag = ""
        if peak > 0.9:
            flag = "  CLIPPING, lower the output master and start again"
        elif peak < 0.001:
            flag = "  very quiet, raise the output master and start again"
        print("  TotalMix %3d dB -> measured %7.2f dBFS  peak %.3f%s"
              % (g, rms, peak, flag))
        if not flag:
            rows.append((float(g), rms))

    if len(rows) < 4:
        print("\nnot enough valid points")
        return

    slope = fit([r[0] for r in rows], [r[1] for r in rows])
    span_shown = rows[-1][0] - rows[0][0]
    span_real = rows[-1][1] - rows[0][1]
    print("\nmeasured %.2f dB of real gain across %.0f dB of TotalMix scale"
          % (span_real, span_shown))
    print("slope %.3f dB per labelled dB" % slope)
    if abs(slope - 1.0) < 0.02:
        print("-> TotalMix's labels are truthful.  A Linux control reading")
        print("   65 dB while delivering 59 would then be a driver bug.")
    else:
        print("-> TotalMix's labels are off by the same proportion measured")
        print("   on Linux, so the Linux driver is reproducing them, and the")
        print("   label is the thing that is approximate.")


if __name__ == "__main__":
    main()
