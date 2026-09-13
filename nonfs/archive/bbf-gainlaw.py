#!/usr/bin/env python3
"""Measure the AN1 mic preamp gain law of an RME Babyface Pro through a
physical analog loop (AN1/2 line out -> input 1), PAD on, phantom OFF.

NOTE ON UNITS (this bit was wrong in the first version of this script):
'Mic 1 Capture Volume' is in dB, range 0..65, not in raw register
steps.  The driver maps dB to the register with

    raw = (db * 8 + 13) / 26          (integer division)

so only 21 distinct register values exist across the 65 dB range, and
the hardware only moves when that quotient changes -- at db =
0,2,5,9,12,15,18,21,...  Sweeping dB one at a time therefore produces
plateaus by design; this script walks the register boundaries instead.

Two measurements are made:

  1. analog master linearity -- master swept over a known digital
     range at fixed gain.  This is the control; it must come out 1:1.
     If it does not, the analog loop itself is non-linear and no gain
     number from it can be trusted.
  2. the gain law -- one point per register step, raw 0..20.

Usage:  ./bbf-gainlaw.py [card] [max_db]   (defaults: card 3, max 65)
        max_db 100 needs the test patch that raises the control ceiling.
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
REC = "/tmp/bbf-gain-rec.wav"
TONE_DBFS = -20.0

MASTER = "AN1/2 Playback Volume"
GAIN = "Mic 1 Capture Volume"
GAIN_MAX_DB = int(sys.argv[2]) if len(sys.argv) > 2 else 65
CLIP = 0.95
FS = 2.0 ** 31


def raw_of_db(db):
    """The driver's dB -> register mapping for mics 0/1."""
    return (db * 8 + 13) // 26


def boundary_dbs():
    """Lowest dB value that reaches each distinct register value."""
    out, seen = [], set()
    for db in range(0, GAIN_MAX_DB + 1):
        r = raw_of_db(db)
        if r not in seen:
            seen.add(r)
            out.append((r, db))
    return out


def make_tone(path, freq=997.0, dbfs=TONE_DBFS, sec=5.0):
    amp = int((FS - 1) * 10 ** (dbfs / 20.0))
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
    if not s:
        return None, 0.0
    acc, peak = 0.0, 0
    for x in s:
        acc += (x / FS) ** 2
        if abs(x) > peak:
            peak = abs(x)
    r = math.sqrt(acc / len(s))
    return (20 * math.log10(r) if r > 0 else None), peak / FS


def cset(name, value, index=None):
    n = "name=" + name + ("" if index is None else ",index=%d" % index)
    subprocess.run(["amixer", "-c", CARD, "cset", n, value],
                   check=True, stdout=subprocess.DEVNULL)


def capture(dur=4):
    rec = subprocess.Popen(
        ["arecord", "-D", DEV, "-f", "S32_LE", "-c", "2", "-r", str(RATE),
         "-d", str(dur), REC], stderr=subprocess.DEVNULL)
    time.sleep(0.4)
    subprocess.run(["aplay", "-D", DEV, TONE], stderr=subprocess.DEVNULL)
    rec.wait()
    return measure(REC)


def set_master(raw):
    cset(MASTER, "%d,%d" % (raw, raw))
    time.sleep(0.25)


def set_gain_db(db):
    cset(GAIN, str(db), index=0)
    time.sleep(0.25)


def fit(points):
    """least-squares slope of y against x"""
    n = len(points)
    sx = sum(p[0] for p in points)
    sy = sum(p[1] for p in points)
    sxx = sum(p[0] * p[0] for p in points)
    sxy = sum(p[0] * p[1] for p in points)
    return (n * sxy - sx * sy) / (n * sxx - sx * sx)


def autolevel(gain_db):
    """Master level that puts this gain just under full scale."""
    master = 16
    set_gain_db(gain_db)
    for _ in range(9):
        set_master(master)
        rms, peak = capture()
        print("  probe: master %5d  peak %.3f  rms %s"
              % (master, peak, "n/a" if rms is None else "%.1f" % rms))
        if peak > CLIP:
            master = max(1, master // 4)
        elif peak < 0.10 and master < 4096:
            master = min(4096, master * 4)
        else:
            return master
    return master


def master_linearity():
    print("\n1. analog master linearity (control experiment)")
    set_gain_db(0)
    pts = []
    for raw in (2048, 1024, 512, 256, 128):
        set_master(raw)
        rms, peak = capture()
        exp = 6 * math.log2(raw / 8192.0)
        if rms is None or peak > CLIP:
            print("   master %5d  expect %+7.2f dB  %s"
                  % (raw, exp, "clipped" if rms else "silence"))
            continue
        print("   master %5d  expect %+7.2f dB  measured %8.2f dBFS  "
              "peak %.3f" % (raw, exp, rms, peak))
        pts.append((exp, rms))
    if len(pts) >= 3:
        s = fit(pts)
        print("   -> slope %.3f dB per dB (1.000 = linear)" % s)
        if abs(s - 1.0) > 0.1:
            print("   -> WARNING: the analog loop is NOT linear; gain "
                  "numbers below are unreliable")
    return


def gain_law(master):
    print("\n2. gain law, one point per register step")
    set_master(master)
    print("%6s %8s %10s %10s %9s" % ("raw", "db set", "claim dB", "measured",
                                     "step"))
    pts, prev = [], None
    for raw, db in boundary_dbs():
        set_gain_db(db)
        rms, peak = capture()
        claim = raw * 13.0 / 4.0
        if rms is None:
            print("%6d %8d %10.2f %10s" % (raw, db, claim, "silence"))
            prev = None
            continue
        step = "" if prev is None else "%+.2f" % (rms - prev)
        flag = "  CLIP" if peak > CLIP else ""
        print("%6d %8d %10.2f %10.2f %9s%s"
              % (raw, db, claim, rms, step, flag))
        if peak <= CLIP and rms > -90.0:
            pts.append((raw, rms))
        prev = rms
    if len(pts) < 5:
        print("\nnot enough usable points")
        return
    s = fit(pts)
    print("\nfitted %.3f dB per register step over raw %d..%d (%d points)"
          % (s, pts[0][0], pts[-1][0], len(pts)))
    print("driver claims 3.250 -> full-range %.1f dB measured vs 65.0 claimed"
          % (s * 20))
    if abs(s - 3.25) < 0.15:
        print("-> the FS gain law fits this unit")
    else:
        print("-> the FS gain law does not fit as written")


def main():
    cset("Loopback Switch", "0")
    make_tone(TONE)
    print("card %s, tone %.1f dBFS at 997 Hz, analog loop AN1/2 out -> in 1"
          % (CARD, TONE_DBFS))
    master_linearity()
    print("\nfinding a safe output level for the top of the gain sweep...")
    master = autolevel(GAIN_MAX_DB)
    print("  using master raw %d (%.1f dB)"
          % (master, 6 * math.log2(master / 8192.0)))
    gain_law(master)
    set_gain_db(0)
    set_master(256)


if __name__ == "__main__":
    main()
