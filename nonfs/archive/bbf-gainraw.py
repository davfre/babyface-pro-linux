#!/usr/bin/env python3
"""Probe the RAW mic-gain register beyond the driver's range.

The driver clamps the gain register to raw 0..20, because that is the
span the Windows captures exercised.  The register is 5 bits, so raw
21..31 exist and have never been tried.  RME documents a 76 dB span
(-11 to +65 dB); at the ~2.97 dB/step measured on this unit that needs
about 26 steps, not 21 -- so raw 20 may not be the hardware maximum.

This writes the register directly over usbfs (bRequest 0x1a, wIndex =
BF_REG_GAIN + mic), exactly as bf_gain_put does: the value in the low
5 bits, repeated with the three transaction-counter flags 0x20 / 0x00
/ 0x40.

TIMING NOTE: the driver re-applies its cached mixer state on every
stream start (bf_cold_init -> babyface_restore_state), so a poke made
before the stream starts is overwritten.  Each point therefore starts
the capture first, poking only once the stream is armed.

Run with sudo (needs /dev/bus/usb write access).

Usage:  sudo ./bbf-gainraw.py [card] [master_raw]
        defaults: card 3, master 1 (about -78 dB, headroom for raw 31)
"""
import array
import math
import os
import re
import subprocess
import sys
import time
import wave

CARD = sys.argv[1] if len(sys.argv) > 1 else "3"
MASTER_RAW = int(sys.argv[2]) if len(sys.argv) > 2 else 1

DEV = "hw:%s,0" % CARD
RATE = 48000
TONE = "/tmp/bbf-raw-tone.wav"
REC = "/tmp/bbf-raw-rec.wav"
TONE_DBFS = -20.0
FS = 2.0 ** 31
CLIP = 0.95

REQ_GAIN = 0x1a
REG_GAIN = 0x0000          # + mic
MIC = 0                    # AN1
COUNTERS = (0x20, 0x00, 0x40)

HERE = os.path.dirname(os.path.abspath(__file__))
USBWRITE_SRC = os.path.join(HERE, "tools", "kernel", "usbwrite.c")
USBWRITE = "/tmp/bbf-usbwrite"


def find_busdev():
    """bus/dev path of the 2a39:3fc0 device, as usbwrite wants it."""
    root = "/sys/bus/usb/devices"
    for name in os.listdir(root):
        d = os.path.join(root, name)
        try:
            vid = open(os.path.join(d, "idVendor")).read().strip()
            pid = open(os.path.join(d, "idProduct")).read().strip()
        except OSError:
            continue
        if vid == "2a39" and pid == "3fc0":
            bus = open(os.path.join(d, "busnum")).read().strip()
            dev = open(os.path.join(d, "devnum")).read().strip()
            return "%03d/%03d" % (int(bus), int(dev))
    return None


def build_usbwrite():
    if os.path.exists(USBWRITE):
        return
    if not os.path.exists(USBWRITE_SRC):
        sys.exit("usbwrite.c not found at %s" % USBWRITE_SRC)
    subprocess.run(["gcc", USBWRITE_SRC, "-o", USBWRITE], check=True)


def poke_gain(busdev, raw):
    """Write the raw gain value the way the driver does."""
    for ctr in COUNTERS:
        subprocess.run([USBWRITE, busdev, "w", "%x" % REQ_GAIN,
                        "%x" % ((raw & 0x1f) | ctr), "%04x" % (REG_GAIN + MIC)],
                       check=True, stdout=subprocess.DEVNULL)
        time.sleep(0.02)


def make_tone(path, dbfs=TONE_DBFS, freq=997.0, sec=5.0):
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


def measure(path, skip=2.0, take=1.5, ch=0):
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


def run_point(busdev, raw):
    """Start the stream, poke the register once it is armed, then play."""
    rec = subprocess.Popen(
        ["arecord", "-D", DEV, "-f", "S32_LE", "-c", "2", "-r", str(RATE),
         "-d", "5", REC], stderr=subprocess.DEVNULL)
    time.sleep(0.7)                 # let stream_work arm + restore state
    poke_gain(busdev, raw)          # now our value sticks
    time.sleep(0.2)
    subprocess.run(["aplay", "-D", DEV, TONE], stderr=subprocess.DEVNULL)
    rec.wait()
    return measure(REC)


def main():
    if os.geteuid() != 0:
        sys.exit("run with sudo (needs /dev/bus/usb write access)")
    busdev = find_busdev()
    if not busdev:
        sys.exit("no 2a39:3fc0 device found -- is it in proprietary mode?")
    build_usbwrite()
    make_tone(TONE)

    cset("Loopback Switch", "0")
    cset("AN1/2 Playback Volume", "%d,%d" % (MASTER_RAW, MASTER_RAW))
    cset("Mic 1 Capture Volume", "0", index=0)
    time.sleep(0.4)

    print("device %s, card %s, master raw %d (%.1f dB)"
          % (busdev, CARD, MASTER_RAW, 6 * math.log2(MASTER_RAW / 8192.0)))
    print("poking bReq 0x%02x wIndex 0x%04x, raw 0..31, low 5 bits + counter\n"
          % (REQ_GAIN, REG_GAIN + MIC))
    print("%6s %12s %9s %8s   %s" % ("raw", "measured", "step", "peak", ""))

    pts, prev, clipped = [], None, False
    for raw in range(0, 32):
        rms, peak = run_point(busdev, raw)
        if rms is None:
            print("%6d %12s" % (raw, "silence"))
            prev = None
            continue
        step = "" if prev is None else "%+.2f" % (rms - prev)
        note = ""
        if raw == 21:
            note = "  <-- past the driver's range"
        if peak > CLIP:
            note += "  CLIP"
            clipped = True
        print("%6d %12.2f %9s %8.3f %s" % (raw, rms, step, peak, note))
        if peak <= CLIP and rms > -95.0:
            pts.append((raw, rms))
        prev = rms
        if clipped:
            print("\nstopping: the ADC is clipping, lower the master and "
                  "re-run to see further")
            break

    # restore: force a real write through the driver so its cache and the
    # hardware agree again
    poke_gain(busdev, 0)
    cset("Mic 1 Capture Volume", "5", index=0)
    cset("Mic 1 Capture Volume", "0", index=0)
    cset("AN1/2 Playback Volume", "256,256")

    if len(pts) < 6:
        print("\nnot enough usable points")
        return
    below = [p for p in pts if p[0] <= 20]
    above = [p for p in pts if p[0] > 20]
    print("\nspan raw %d..%d: %.1f dB"
          % (pts[0][0], pts[-1][0], pts[-1][1] - pts[0][1]))
    if below:
        print("raw 0..20 span: %.1f dB" % (below[-1][1] - below[0][1]))
    if above:
        gained = above[-1][1] - below[-1][1] if below else 0.0
        print("raw 21..%d added a further %.1f dB -> the driver's range is "
              "short" % (above[-1][0], gained))
        if gained < 1.0:
            print("  (...or raw 20 really is the hardware maximum)")
    else:
        print("no usable points past raw 20")


if __name__ == "__main__":
    main()
