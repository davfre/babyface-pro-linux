#!/usr/bin/env python3
"""Measure the AN1/2 output-master volume law on an RME Babyface Pro,
using the device's own digital loopback.  Nothing is ever audible, so
monitors can stay off.

The snd-usb-babyface-pro driver derives the master law from Babyface Pro
FS captures: raw = 0x2000 * 2**(dB/6), i.e. raw 8192 = 0 dB, 16384 = +6 dB.
This checks whether that holds on non-FS hardware: with a tone of known
level looped back, measured level should track expected level 1:1, and
every delta column should read the same constant.

Usage:  ./bbf-masterlaw.py [card]        (card defaults to 3)
"""
import array
import math
import subprocess
import sys
import time
import wave

CARD = sys.argv[1] if len(sys.argv) > 1 else "3"
DEV = "hw:%s,0" % CARD
RATE = 48000
TONE = "/tmp/bbf-tone-s32.wav"
REC = "/tmp/bbf-rec.wav"
TONE_DBFS = -20.0
MASTER = "AN1/2 Playback Volume"

# raw master values, spanning +6 dB down to -36 dB in 6 dB steps
POINTS = [16384, 8192, 4096, 2048, 1024, 512, 256]


def make_tone(path, freq=440.0, dbfs=TONE_DBFS, sec=6.0):
    """S32_LE stereo tone, sample left-justified (the driver's format)."""
    amp = int((2 ** 31 - 1) * 10 ** (dbfs / 20.0))
    n = int(RATE * sec)
    a = array.array("i")
    for i in range(n):
        v = int(amp * math.sin(2 * math.pi * freq * i / RATE))
        a.append(v)
        a.append(v)
    w = wave.open(path, "wb")
    w.setnchannels(2)
    w.setsampwidth(4)
    w.setframerate(RATE)
    w.writeframes(a.tobytes())
    w.close()


def rms_dbfs(path, skip=1.5, take=2.0):
    """RMS of channel 0 over a settled window, in dBFS."""
    w = wave.open(path, "rb")
    nch = w.getnchannels()
    total = w.getnframes()
    start = min(int(skip * RATE), total)
    w.setpos(start)
    want = min(int(take * RATE), total - start)
    if want <= 0:
        return None
    a = array.array("i")
    a.frombytes(w.readframes(want))
    w.close()
    ch0 = a[0::nch]
    if not ch0:
        return None
    acc = 0.0
    for x in ch0:
        f = x / 2 ** 31
        acc += f * f
    r = math.sqrt(acc / len(ch0))
    return 20 * math.log10(r) if r > 0 else None


def cset(name, value):
    subprocess.run(["amixer", "-c", CARD, "cset", "name=" + name, value],
                   check=True, stdout=subprocess.DEVNULL)


def run_point(raw):
    cset(MASTER, "%d,%d" % (raw, raw))
    time.sleep(0.3)
    rec = subprocess.Popen(
        ["arecord", "-D", DEV, "-f", "S32_LE", "-c", "2", "-r", str(RATE),
         "-d", "5", REC], stderr=subprocess.DEVNULL)
    time.sleep(0.4)
    subprocess.run(["aplay", "-D", DEV, TONE], stderr=subprocess.DEVNULL)
    rec.wait()
    return rms_dbfs(REC)


def main():
    cset("Loopback Switch", "1")
    make_tone(TONE)
    print("card %s, tone %.1f dBFS at 440 Hz, loopback on" % (CARD, TONE_DBFS))
    print("law under test: raw = 8192 * 2**(dB/6)\n")
    print("%8s %12s %14s %9s" % ("raw", "expect dB", "measured", "delta"))
    rows = []
    for raw in POINTS:
        expect = 6 * math.log2(raw / 8192.0)
        got = run_point(raw)
        if got is None:
            print("%8d %12.2f %14s" % (raw, expect, "silence"))
            continue
        delta = got - (TONE_DBFS + expect)
        rows.append((expect, got, delta))
        print("%8d %12.2f %14.2f %9.2f" % (raw, expect, got, delta))

    cset(MASTER, "8192,8192")
    if len(rows) < 3:
        print("\nnot enough points captured to judge the law")
        return
    deltas = [r[2] for r in rows]
    spread = max(deltas) - min(deltas)
    offset = sum(deltas) / len(deltas)
    print("\ndelta spread %.2f dB, mean offset %.2f dB" % (spread, offset))
    if spread < 1.0:
        print("-> law tracks: the FS master curve fits this unit "
              "(a constant offset is just loopback path gain)")
    else:
        print("-> law does NOT track: the master curve differs on this unit, "
              "the delta column is the error vs the FS calibration")


if __name__ == "__main__":
    main()
