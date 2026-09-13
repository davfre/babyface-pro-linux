#!/usr/bin/env python3
"""Print the level coming back through the analog loop, once or repeatedly.

For measurements where something other than a script changes the gain: the
front panel wheel, or a knob in another application. Leave it running, make
a change, and read the next line.

    ./bbf-level.py --card FS                 one reading
    ./bbf-level.py --card FS --repeat        a reading every few seconds

Needs an analog output patched to input 1, PAD on, phantom OFF.
"""
import argparse
import array
import math
import subprocess
import sys
import time
import wave

RATE = 48000
FS = 2.0 ** 31
TONE = "/tmp/bbf-level-tone.wav"
REC = "/tmp/bbf-level-rec.wav"


def make_tone(path, dbfs=-20.0, freq=997.0, sec=5.0):
    amp = (FS - 1) * 10 ** (dbfs / 20.0)
    a = array.array("i")
    for i in range(int(RATE * sec)):
        v = int(amp * math.sin(2 * math.pi * freq * i / RATE))
        a.append(v)
        a.append(v)
    w = wave.open(path, "wb")
    w.setnchannels(2)
    w.setsampwidth(4)
    w.setframerate(RATE)
    w.writeframes(a.tobytes())
    w.close()


def measure(path, skip=1.2, take=1.5, ch=0):
    w = wave.open(path, "rb")
    nch, total = w.getnchannels(), w.getnframes()
    start = min(int(skip * RATE), total)
    w.setpos(start)
    want = min(int(take * RATE), total - start)
    if want <= 0:
        return None, 0.0
    a = array.array("i")
    a.frombytes(w.readframes(want))
    w.close()
    s = a[ch::nch]
    acc, peak = 0.0, 0
    for x in s:
        acc += (x / FS) ** 2
        if abs(x) > peak:
            peak = abs(x)
    r = math.sqrt(acc / len(s))
    return (20 * math.log10(r) if r > 0 else None), peak / FS


def capture(pcm):
    rec = subprocess.Popen(
        ["arecord", "-D", pcm, "-f", "S32_LE", "-c", "2", "-r", str(RATE),
         "-d", "4", REC], stderr=subprocess.DEVNULL)
    time.sleep(0.4)
    subprocess.run(["aplay", "-D", pcm, TONE], stderr=subprocess.DEVNULL)
    rec.wait()
    return measure(REC)


def driver_gain(card):
    """What the driver believes the gain is, in dB."""
    try:
        out = subprocess.run(
            ["amixer", "-c", card, "cget", "name=Mic 1 Capture Volume"],
            capture_output=True, text=True, check=True).stdout
        for line in out.splitlines():
            if line.strip().startswith(": values="):
                return line.split("=")[1].strip()
    except Exception:
        pass
    return "?"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--card", default="FS")
    ap.add_argument("--device", default="0")
    ap.add_argument("--repeat", action="store_true")
    args = ap.parse_args()

    pcm = ("hw:%s,%s" % (args.card, args.device)
           if not args.card.isdigit() else "hw:%s,%s" % (args.card,
                                                         args.device))
    make_tone(TONE)
    first = None
    print("reading level on input 1.  Ctrl-C to stop.\n")
    print("%8s %12s %8s %14s %12s"
          % ("reading", "level dBFS", "peak", "driver says dB", "vs first"))
    n = 0
    try:
        while True:
            n += 1
            rms, peak = capture(pcm)
            g = driver_gain(args.card)
            if rms is None:
                print("%8d %12s" % (n, "silence"))
            else:
                if first is None:
                    first = rms
                print("%8d %12.2f %8.3f %14s %+12.2f"
                      % (n, rms, peak, g, rms - first))
            if not args.repeat:
                break
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
