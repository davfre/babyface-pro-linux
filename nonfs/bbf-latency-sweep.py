#!/usr/bin/env python3
"""Count xruns across period sizes on any ALSA device, full duplex.

Written to compare the same Babyface Pro in its two modes on equal terms:

    class compliant   handled by snd-usb-audio
    proprietary       handled by snd-usb-babyface-pro

It talks to the hardware device directly (hw:), so PipeWire's quantum
settings play no part.  Check yours with `pw-metadata -n settings`; a
pinned min-quantum will cap anything routed through PipeWire but has no
effect here.

For each period size it runs aplay and arecord together for a fixed time
and counts the xrun reports both of them print.  Full duplex matters:
this device only advances audio when both directions have work pending,
and half duplex numbers would flatter it.

Usage:
    ./bbf-latency-sweep.py --card FS
    ./bbf-latency-sweep.py --card ProNNNNNNNN --rate 48000
    ./bbf-latency-sweep.py --card FS --periods 32 64 128 256 --seconds 20

Note the card id changes between modes, since the two drivers name the
card differently.  `cat /proc/asound/cards` lists them.
"""
import argparse
import array
import math
import re
import subprocess
import sys
import tempfile
import wave

FS = 2.0 ** 31
XRUN = re.compile(r"underrun|overrun|xrun", re.I)


def make_tone(path, rate, fmt_width, dbfs=-20.0, freq=440.0, sec=60.0):
    """A long tone so aplay never runs out before the timer does."""
    amp = (2 ** (8 * fmt_width - 1) - 1) * 10 ** (dbfs / 20.0)
    typecode = {2: "h", 4: "i"}[fmt_width]
    a = array.array(typecode)
    for i in range(int(rate * sec)):
        v = int(amp * math.sin(2 * math.pi * freq * i / rate))
        a.append(v)
        a.append(v)
    w = wave.open(path, "wb")
    w.setnchannels(2)
    w.setsampwidth(fmt_width)
    w.setframerate(rate)
    w.writeframes(a.tobytes())
    w.close()


def supported_format(dev, rate):
    """Pick a format the device accepts: S32_LE, else S24_3LE, else S16_LE."""
    for fmt, width in (("S32_LE", 4), ("S24_3LE", 3), ("S16_LE", 2)):
        r = subprocess.run(
            ["arecord", "-D", dev, "-f", fmt, "-c", "2", "-r", str(rate),
             "-d", "1", "/dev/null"],
            capture_output=True, text=True)
        if r.returncode == 0:
            return fmt, width
    return None, None


def run_point(dev, rate, fmt, tone, period, seconds):
    buf = period * 4
    common = ["-D", dev, "-f", fmt, "-c", "2", "-r", str(rate),
              "--period-size=%d" % period, "--buffer-size=%d" % buf, "-v"]
    rec = subprocess.Popen(["arecord"] + common + ["-d", str(seconds),
                                                   "/dev/null"],
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.PIPE, text=True)
    play = subprocess.Popen(["aplay"] + common + ["-d", str(seconds), tone],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE, text=True)
    _, perr = play.communicate()
    _, rerr = rec.communicate()
    if play.returncode != 0 and not perr.strip():
        return None, None, "aplay failed"
    if "Unable to install hw params" in (perr + rerr):
        return None, None, "rejected"
    return (len(XRUN.findall(perr)), len(XRUN.findall(rerr)), None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--card", required=True,
                    help="ALSA card id or index, from /proc/asound/cards")
    ap.add_argument("--device", default="0", help="PCM device (default 0)")
    ap.add_argument("--rate", type=int, default=48000)
    ap.add_argument("--periods", type=int, nargs="+",
                    default=[16, 32, 64, 128, 256, 512, 1024])
    ap.add_argument("--seconds", type=int, default=15)
    args = ap.parse_args()

    dev = ("hw:%s,%s" % (args.card, args.device))
    fmt, width = supported_format(dev, args.rate)
    if not fmt:
        sys.exit("no usable format on %s at %d Hz" % (dev, args.rate))

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as t:
        tone = t.name
    make_tone(tone, args.rate, 2 if width == 3 else width)

    print("device %s, %d Hz, %s, %d s per point, full duplex"
          % (dev, args.rate, fmt, args.seconds))
    print("PipeWire is not involved; this is the raw ALSA device\n")
    print("%8s %10s %12s %12s %10s"
          % ("period", "ms", "play xruns", "rec xruns", "verdict"))

    for p in sorted(args.periods):
        pl, rc, err = run_point(dev, args.rate, fmt, tone, p, args.seconds)
        ms = 1000.0 * p / args.rate
        if err:
            print("%8d %10.2f %12s %12s %10s" % (p, ms, "-", "-", err))
            continue
        verdict = "clean" if (pl + rc) == 0 else "XRUN"
        print("%8d %10.2f %12d %12d %10s" % (p, ms, pl, rc, verdict))

    print("\nThe lowest period with 0 xruns over %d s is the floor for this "
          "mode." % args.seconds)
    print("Run the same command in the other mode and compare.")


if __name__ == "__main__":
    main()
