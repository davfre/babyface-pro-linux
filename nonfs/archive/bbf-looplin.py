#!/usr/bin/env python3
"""Is the analog loop linear?

Every device control is frozen; only the DIGITAL amplitude of the test
tone changes, and that amplitude is exact by construction.  So the
measured slope is a property of the loop alone (DAC -> XLR -> cable ->
preamp -> ADC), with no device law in the path.

  slope ~1.000  -> the loop is linear.  Any deviation seen when a
                   device control is swept belongs to that control's
                   law, not to the measurement chain.
  slope <1.000  -> the loop compresses, and every law measured through
                   it must be divided by this slope.

Run it at the same master and gain the gain sweep ended at, so the
operating point matches.

Usage:  ./bbf-looplin.py [card] [master_raw] [gain_db]
        defaults: card 3, master 4, gain 64
"""
import array
import math
import subprocess
import sys
import time
import wave

CARD = sys.argv[1] if len(sys.argv) > 1 else "3"
MASTER_RAW = int(sys.argv[2]) if len(sys.argv) > 2 else 4
GAIN_DB = int(sys.argv[3]) if len(sys.argv) > 3 else 64

DEV = "hw:%s,0" % CARD
RATE = 48000
TONE = "/tmp/bbf-lin-tone.wav"
REC = "/tmp/bbf-lin-rec.wav"
FS = 2.0 ** 31
CLIP = 0.95

# digital tone levels to test, dBFS
LEVELS = [-14.0, -20.0, -26.0, -32.0, -38.0, -44.0, -50.0]


def make_tone(path, dbfs, freq=997.0, sec=5.0):
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


def cset(name, value, index=None):
    n = "name=" + name + ("" if index is None else ",index=%d" % index)
    subprocess.run(["amixer", "-c", CARD, "cset", n, value],
                   check=True, stdout=subprocess.DEVNULL)


def capture():
    rec = subprocess.Popen(
        ["arecord", "-D", DEV, "-f", "S32_LE", "-c", "2", "-r", str(RATE),
         "-d", "4", REC], stderr=subprocess.DEVNULL)
    time.sleep(0.4)
    subprocess.run(["aplay", "-D", DEV, TONE], stderr=subprocess.DEVNULL)
    rec.wait()
    return measure(REC)


def main():
    cset("Loopback Switch", "0")
    cset("AN1/2 Playback Volume", "%d,%d" % (MASTER_RAW, MASTER_RAW))
    cset("Mic 1 Capture Volume", str(GAIN_DB), index=0)
    time.sleep(0.4)
    print("card %s, master raw %d, gain %d dB, both frozen for the whole run"
          % (CARD, MASTER_RAW, GAIN_DB))
    print("only the digital tone amplitude changes\n")
    print("%10s %12s %9s %8s" % ("tone dBFS", "measured", "step", "peak"))
    pts, prev = [], None
    for lvl in LEVELS:
        make_tone(TONE, lvl)
        rms, peak = capture()
        if rms is None:
            print("%10.1f %12s" % (lvl, "silence"))
            prev = None
            continue
        step = "" if prev is None else "%+.2f" % (rms - prev)
        flag = "  CLIP" if peak > CLIP else ""
        print("%10.1f %12.2f %9s %8.3f%s" % (lvl, rms, step, peak, flag))
        if peak <= CLIP and rms > -95.0:
            pts.append((lvl, rms))
        prev = rms

    if len(pts) < 4:
        print("\nnot enough usable points")
        return
    n = len(pts)
    sx = sum(p[0] for p in pts)
    sy = sum(p[1] for p in pts)
    sxx = sum(p[0] * p[0] for p in pts)
    sxy = sum(p[0] * p[1] for p in pts)
    slope = (n * sxy - sx * sy) / (n * sxx - sx * sx)
    print("\nloop slope %.3f dB per dB over %d points" % (slope, n))
    if abs(slope - 1.0) < 0.02:
        print("-> the loop is linear.  The 0.93 seen when sweeping the")
        print("   master belongs to the master's own law: the 8-bit")
        print("   register is about %.3f dB/code here, not the 0.5 the"
              % (0.5 * slope / 0.930))
        print("   driver assumes.  The gain-law numbers stand as measured.")
    else:
        print("-> the loop itself is non-linear (%.3f).  Divide every law"
              % slope)
        print("   measured through it by this slope: the gain law becomes")
        print("   %.3f dB per register step, %.1f dB full range."
              % (2.916 / slope, 2.916 / slope * 20))


if __name__ == "__main__":
    main()
