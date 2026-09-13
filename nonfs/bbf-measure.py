#!/usr/bin/env python3
"""bbf-measure v2 -- measurement probes for the RME Babyface Pro under
snd-usb-babyface-pro.

Supersedes the ad-hoc bbf-masterlaw.py / bbf-gainlaw.py / bbf-looplin.py.
Versioned deliberately: the script is part of the result, so it should not
be edited in place once numbers have been quoted from it.

SAFETY RULES THIS SCRIPT FOLLOWS
  * only values the driver itself accepts are ever written -- no raw
    register pokes, nothing outside a control's declared range
  * the cable tests refuse to run unless you pass --cable, so nothing
    drives an analog input by accident
  * gain and master are always restored on exit, including on Ctrl-C
  * the autolevel search steps in 6 dB and stops below clipping, instead
    of overshooting to full scale

TESTS
  digital    master law through the device's own Loopback.  No cable.
  noise      gain law inferred from the preamp noise floor.  No cable.
  linearity  is the analog loop linear?  Device controls frozen, only the
             digital tone amplitude varies.  Needs the cable.
  gain       gain law, one point per register step.  Needs the cable.
  pad        A/B the PAD relay at a fixed operating point.  Needs the cable.

CABLE TESTS EXPECT: an analog output patched to input 1, PAD ON, PHANTOM
POWER OFF.  Check phantom before connecting anything -- 48 V into a line
output is the one combination here that can damage hardware.

EXAMPLES
  ./bbf-measure-v2.py --tests digital
  ./bbf-measure-v2.py --tests noise
  ./bbf-measure-v2.py --cable --tests linearity gain pad
"""
import argparse
import array
import math
import subprocess
import sys
import time
import wave

VERSION = "3.2"
RATE = 48000
FS = 2.0 ** 31
TONE = "/tmp/bbf-v2-tone.wav"
REC = "/tmp/bbf-v2-rec.wav"

MASTER = "AN1/2 Playback Volume"
GAIN = "Mic 1 Capture Volume"
LOOPBACK = "Loopback Switch"
PAD_NUMIDS = (15, 16)
PHANTOM_NUMIDS = (13, 14)

MASTER_UNITY = 8192          # 0 dB
MASTER_SAFE = 256            # about -30 dB, where we leave things
MASTER_MIN = 2               # below this the 8-bit master can mute
MASTER_MAX = 4096
CLIP = 0.90
PEAK_LO, PEAK_HI = 0.15, 0.60

GAIN_MAX_DB = 65             # the driver's declared ceiling; never exceeded
PAD_MASTER = 64              # fixed operating point for the PAD A/B
GAIN_STEP = 5                # dB between points in the gain sweep
GAIN_MASTER = None           # fixed master for the gain sweep, or None to autolevel
GAIN_FROM = 0                # gain sweep range, dB
GAIN_TO = None               # defaults to GAIN_MAX_DB


# ---------------------------------------------------------------- helpers

def db_of_master(raw):
    return 6 * math.log2(raw / float(MASTER_UNITY))


def gain_points(step=5):
    """dB values to sweep.

    v3.0 deliberately knows nothing about how the driver encodes gain.
    Earlier versions sampled "one point per distinct register value" using
    their own copy of the driver's arithmetic, so when the driver's
    encoding was corrected the sampling silently went stale and the sweep
    kept walking the old grid.

    Sweeping plain dB works against any version. If the control quantises,
    the measurement shows it as plateaus, which is a result rather than a
    problem. The adjacent triplet at 30/31/32 is there to make 1 dB
    resolution visible either way: three distinct levels means it resolves,
    one level repeated means it does not.
    """
    lo = GAIN_FROM
    hi = GAIN_MAX_DB if GAIN_TO is None else GAIN_TO
    pts = set(range(lo, hi + 1, step))
    if step > 1:
        pts |= {d for d in (30, 31, 32) if lo <= d <= hi}
    pts.add(hi)
    return sorted(pts)


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
    if not s:
        return None, 0.0
    acc, peak = 0.0, 0
    for x in s:
        acc += (x / FS) ** 2
        if abs(x) > peak:
            peak = abs(x)
    r = math.sqrt(acc / len(s))
    return (20 * math.log10(r) if r > 0 else None), peak / FS


def fit(points):
    n = len(points)
    sx = sum(p[0] for p in points)
    sy = sum(p[1] for p in points)
    sxx = sum(p[0] * p[0] for p in points)
    sxy = sum(p[0] * p[1] for p in points)
    den = n * sxx - sx * sx
    return None if den == 0 else (n * sxy - sx * sy) / den


class Dev:
    def __init__(self, card):
        self.card = card
        self.pcm = "hw:CARD=%s,0" % card if not card.isdigit() else \
                   "hw:%s,0" % card

    def cset(self, name, value, index=None):
        n = "name=" + name + ("" if index is None else ",index=%d" % index)
        subprocess.run(["amixer", "-c", self.card, "cset", n, value],
                       check=True, stdout=subprocess.DEVNULL)

    def cset_numid(self, numid, value):
        subprocess.run(["amixer", "-c", self.card, "cset",
                        "numid=%d" % numid, str(value)],
                       check=True, stdout=subprocess.DEVNULL)

    def cget(self, name, index=None):
        n = "name=" + name + ("" if index is None else ",index=%d" % index)
        r = subprocess.run(["amixer", "-c", self.card, "cget", n],
                           capture_output=True, text=True, check=True)
        return r.stdout

    def master(self, raw):
        self.cset(MASTER, "%d,%d" % (raw, raw))
        time.sleep(0.25)

    def gain(self, db, index=0):
        db = max(0, min(GAIN_MAX_DB, int(db)))
        self.cset(GAIN, str(db), index=index)
        time.sleep(0.25)

    def capture(self, dur=4, play=True):
        rec = subprocess.Popen(
            ["arecord", "-D", self.pcm, "-f", "S32_LE", "-c", "2",
             "-r", str(RATE), "-d", str(dur), REC],
            stderr=subprocess.DEVNULL)
        time.sleep(0.4)
        if play:
            subprocess.run(["aplay", "-D", self.pcm, TONE],
                           stderr=subprocess.DEVNULL)
        rec.wait()
        return measure(REC)

    def restore(self):
        """Always leave the device quiet and in a known state."""
        try:
            self.gain(0, index=0)
            self.gain(0, index=1)
            self.cset(LOOPBACK, "0")
            self.master(MASTER_SAFE)
        except Exception as e:                       # noqa: BLE001
            print("  (restore failed: %s)" % e, file=sys.stderr)

    def autolevel(self, gain_db):
        """Find a master that lands the peak in a safe window.  Steps by
        6 dB so it does not overshoot into clipping the way v1 did."""
        self.gain(gain_db)
        master = 64
        last = None
        for _ in range(10):
            master = max(MASTER_MIN, min(MASTER_MAX, master))
            self.master(master)
            rms, peak = self.capture()
            print("   probe master %5d (%+6.1f dB)  peak %.3f  rms %s"
                  % (master, db_of_master(master), peak,
                     "n/a" if rms is None else "%.1f" % rms))
            if peak > PEAK_HI:
                nxt = master // 2
            elif peak < PEAK_LO:
                nxt = master * 2
            else:
                return master
            if nxt == last or nxt == master:
                return master
            last, master = master, nxt
        return master


# ------------------------------------------------------------------ tests

def t_digital(dev):
    print("\n== digital: output master law through the device Loopback ==")
    print("   (no cable needed; this is the purely digital path)")
    dev.cset(LOOPBACK, "1")
    dev.gain(0)
    make_tone(TONE, -20.0)
    print("\n%8s %11s %13s %9s" % ("raw", "expect dB", "measured", "delta"))
    pts = []
    for raw in (16384, 8192, 4096, 2048, 1024, 512, 256):
        dev.master(raw)
        rms, peak = dev.capture()
        exp = db_of_master(raw)
        if rms is None:
            print("%8d %11.2f %13s" % (raw, exp, "silence"))
            continue
        print("%8d %11.2f %13.2f %9.2f" % (raw, exp, rms, rms - exp + 20.0))
        pts.append((exp, rms))
    dev.cset(LOOPBACK, "0")
    s = fit(pts)
    if s is not None:
        deltas = [p[1] - p[0] for p in pts]
        print("\n   slope %.3f dB/dB, delta spread %.2f dB"
              % (s, max(deltas) - min(deltas)))
        print("   (a constant delta is just path gain; the spread is what "
              "matters)")


def t_noise(dev):
    print("\n== noise: gain law from the preamp noise floor ==")
    print("   (no cable; the preamp amplifies its own input noise, so the")
    print("    measured floor tracks real gain at the top of the range)")
    dev.cset(LOOPBACK, "0")
    dev.master(MASTER_SAFE)
    print("\n%8s %12s %10s" % ("db set", "measured", "step"))
    pts, prev = [], None
    for db in gain_points(GAIN_STEP):
        dev.gain(db)
        rms, peak = dev.capture(play=False)
        if rms is None:
            print("%8d %12s" % (db, "silence"))
            prev = None
            continue
        step = "" if prev is None else "%+.2f" % (rms - prev)
        print("%8d %12.2f %10s" % (db, rms, step))
        pts.append((float(db), rms))
        prev = rms
    top = [p for p in pts if p[0] >= 30]
    s = fit(top)
    if s is not None:
        print("\n   %.3f dB per dB of control over the top of the range "
              "(30 dB and up)" % s)
        print("   below that the converter's own noise floor dominates and "
              "the curve flattens")


def t_linearity(dev):
    print("\n== linearity: is the analog loop linear? ==")
    print("   (device controls frozen; only the digital tone level varies)")
    dev.cset(LOOPBACK, "0")
    dev.gain(GAIN_MAX_DB)
    master = dev.autolevel(GAIN_MAX_DB)
    print("   operating point: master %d (%+.1f dB), gain %d dB\n"
          % (master, db_of_master(master), GAIN_MAX_DB))
    print("%10s %12s %9s %8s" % ("tone dBFS", "measured", "step", "peak"))
    rows, prev = [], None
    for lvl in (-14.0, -20.0, -26.0, -32.0, -38.0, -44.0, -50.0):
        make_tone(TONE, lvl)
        rms, peak = dev.capture()
        if rms is None:
            print("%10.1f %12s" % (lvl, "silence"))
            prev = None
            continue
        step = "" if prev is None else "%+.2f" % (rms - prev)
        print("%10.1f %12.2f %9s %8.3f%s"
              % (lvl, rms, step, peak, "  CLIP" if peak > CLIP else ""))
        rows.append((lvl, rms, peak))
        prev = rms
    # walk down from the top and stop where a step departs from nominal:
    # below that the noise floor dominates and the points are not usable.
    good = []
    for i, (lvl, rms, peak) in enumerate(rows):
        if peak > CLIP:
            continue
        if i > 0:
            nominal = rows[i][0] - rows[i - 1][0]
            if abs((rms - rows[i - 1][1]) - nominal) > 0.5:
                break
        good.append((lvl, rms))
    s = fit(good)
    if s is not None:
        print("\n   slope %.3f dB/dB over the %d points above the noise "
              "floor" % (s, len(good)))
        if abs(s - 1.0) < 0.02:
            print("   -> the loop is linear; laws measured through it "
                  "stand as measured")
        else:
            print("   -> the loop is NOT linear; divide other laws by "
                  "this slope")


def t_gain(dev):
    """Sweep gain, measuring the tone AND the noise floor at every point.

    v3.2: each point is captured twice, once with the tone playing and once
    silent. Without that you cannot tell a gain curve from the amplified
    noise floor rising, because both track real gain. Any point whose tone
    is not clearly above its own noise is marked and excluded.
    """
    print("\n== gain: mic preamp law ==")
    dev.cset(LOOPBACK, "0")
    make_tone(TONE, -20.0)
    if GAIN_MASTER is not None:
        master = GAIN_MASTER
        print("   master %d (%+.1f dB), fixed" % (master, db_of_master(master)))
        dev.gain(0)
    else:
        master = dev.autolevel(GAIN_MAX_DB)
        print("   master %d (%+.1f dB), autolevelled"
              % (master, db_of_master(master)))
    dev.master(master)
    print("   each point measured twice, tone and silence\n")
    print("%8s %11s %11s %8s %9s %8s"
          % ("db set", "tone", "noise", "S/N", "step", "peak"))
    pts, prev = [], None
    for db in gain_points(GAIN_STEP):
        dev.gain(db)
        tone_rms, peak = dev.capture()
        noise_rms, _ = dev.capture(play=False)
        if tone_rms is None:
            print("%8d %11s" % (db, "silence"))
            prev = None
            continue
        nf = noise_rms if noise_rms is not None else -200.0
        snr = tone_rms - nf
        why = ""
        if peak > CLIP:
            why = "  CLIP"
        elif snr < 6.0:
            why = "  NO SIGNAL (measuring noise)"
        step = "" if prev is None else "%+.2f" % (tone_rms - prev)
        print("%8d %11.2f %11.2f %8.1f %9s %8.3f%s"
              % (db, tone_rms, nf, snr, step, peak, why))
        if not why:
            pts.append((float(db), tone_rms))
            prev = tone_rms
        else:
            prev = None

    if len(pts) < 4:
        print("\n   too few valid points to fit.  Adjust --gain-master: the")
        print("   tone must sit above the noise floor and below clipping at")
        print("   every gain in the sweep, which may not be possible across")
        print("   the whole range in one run.")
        return

    drops = [(pts[i - 1][0], pts[i][0], pts[i][1] - pts[i - 1][1])
             for i in range(1, len(pts)) if pts[i][1] < pts[i - 1][1] - 0.3]
    if drops:
        print("\n   NON-MONOTONIC at %d points:" % len(drops))
        for a, b, d in drops[:8]:
            print("      %g -> %g dB : %+.2f dB" % (a, b, d))

    s = fit(pts)
    print("\n   %.3f dB measured per dB of control (1.000 = correct), over"
          % s)
    print("   %d valid points from %g to %g dB"
          % (len(pts), pts[0][0], pts[-1][0]))


def t_pad(dev):
    print("\n== pad: does the PAD relay change anything? ==")
    print("   (A/B at a fixed operating point; both are normal driver")
    print("    writes, nothing out of range)")
    dev.cset(LOOPBACK, "0")
    make_tone(TONE, -20.0)
    # v2.3: no autolevel at all.  The search was the problem: it walked
    # up to master 256, where PAD-off collapses into full-scale clipping
    # (a jump of ~22 dB for a 6 dB master step -- unexplained, see notes),
    # and then A/B'd against a square wave, reporting +28 dB when the real
    # figure is around 11.  A fixed, low master keeps both states valid.
    master = PAD_MASTER
    print("   fixed master %d (%+.1f dB), no autolevel"
          % (master, db_of_master(master)))
    dev.master(master)
    dev.gain(30)
    out = {}
    for state in (1, 0, 1):
        dev.cset_numid(PAD_NUMIDS[0], state)
        time.sleep(0.5)
        rms, peak = dev.capture()
        print("   PAD %-3s  measured %s  peak %.3f%s"
              % ("on" if state else "off",
                 "silence" if rms is None else "%8.2f dBFS" % rms, peak,
                 "  CLIP - result invalid" if peak > CLIP else ""))
        if rms is not None:
            out.setdefault(state, []).append(rms)
    dev.cset_numid(PAD_NUMIDS[0], 1)
    if 1 in out and 0 in out:
        on = sum(out[1]) / len(out[1])
        off = sum(out[0]) / len(out[0])
        d = off - on
        repeat = max(out[1]) - min(out[1]) if len(out[1]) > 1 else 0.0
        print("\n   PAD on  %8.2f dBFS (two readings agree to %.2f dB)"
              % (on, repeat))
        print("   PAD off %8.2f dBFS" % off)
        print("   PAD off is %+.2f dB relative to PAD on" % d)
        if abs(d) < 0.5:
            print("   -> the PAD control is not changing the signal path")
        else:
            print("   -> PAD depth is %.1f dB (RME publish -11 dB as the "
                  "bottom of the gain range)" % d)


def t_padsweep(dev):
    print("\n== padsweep: does PAD depth vary across the gain range? ==")
    print("   (fixed master, PAD A/B repeated at several gains.  A passive")
    print("    attenuator ahead of the preamp would give a constant depth;")
    print("    a depth that moves means the relay changes the input stage.)")
    dev.cset(LOOPBACK, "0")
    make_tone(TONE, -20.0)
    master = PAD_MASTER
    print("   fixed master %d (%+.1f dB)\n" % (master, db_of_master(master)))
    dev.master(master)
    print("%8s %12s %12s %10s %8s" % ("gain dB", "PAD on", "PAD off",
                                      "depth", "peak off"))
    rows = []
    for g in (0, 10, 20, 30, 40, 50, 60, 65):
        dev.gain(g)
        dev.cset_numid(PAD_NUMIDS[0], 1)
        time.sleep(0.4)
        on, on_pk = dev.capture()
        dev.cset_numid(PAD_NUMIDS[0], 0)
        time.sleep(0.4)
        off, off_pk = dev.capture()
        dev.cset_numid(PAD_NUMIDS[0], 1)
        if on is None or off is None:
            print("%8d %12s" % (g, "silence"))
            continue
        bad = off_pk > CLIP or on_pk > CLIP
        note = "  CLIP - skipped" if bad else ""
        print("%8d %12.2f %12.2f %10.2f %8.3f%s"
              % (g, on, off, off - on, off_pk, note))
        if not bad and on > -95.0:
            rows.append((g, off - on))
    dev.cset_numid(PAD_NUMIDS[0], 1)
    if len(rows) < 3:
        print("\n   not enough valid points; try --pad-master 16")
        return
    depths = [r[1] for r in rows]
    spread = max(depths) - min(depths)
    print("\n   depth %.2f..%.2f dB over gain %d..%d, spread %.2f dB"
          % (min(depths), max(depths), rows[0][0], rows[-1][0], spread))
    if spread < 0.5:
        print("   -> constant: PAD behaves as a plain attenuator ahead of "
              "the gain stage")
    else:
        print("   -> NOT constant: the relay is doing something other than "
              "a fixed pad")


TESTS = {
    "digital": (t_digital, False),
    "noise": (t_noise, False),
    "linearity": (t_linearity, True),
    "gain": (t_gain, True),
    "pad": (t_pad, True),
    "padsweep": (t_padsweep, True),
}


def main():
    global PAD_MASTER, GAIN_MASTER, GAIN_STEP, GAIN_FROM, GAIN_TO
    ap = argparse.ArgumentParser(
        description="Babyface Pro measurement probes (v%s)" % VERSION)
    ap.add_argument("--card", default="FS",
                    help="ALSA card id or index (default: FS, by name, so "
                         "it survives reloads that renumber the card)")
    ap.add_argument("--cable", action="store_true",
                    help="an analog output IS patched to input 1, PAD on, "
                         "phantom off.  Required by linearity/gain/pad.")
    ap.add_argument("--gain-master", type=int, default=None,
                    help="fixed master raw for the gain sweep; use the same "
                         "value either side of a driver change so the two "
                         "runs are comparable")
    ap.add_argument("--gain-from", type=int, default=GAIN_FROM,
                    help="first dB of the gain sweep (default 0)")
    ap.add_argument("--gain-to", type=int, default=None,
                    help="last dB of the gain sweep (default 65)")
    ap.add_argument("--gain-step", type=int, default=GAIN_STEP,
                    help="dB between points in the gain sweep (default 5)")
    ap.add_argument("--pad-master", type=int, default=PAD_MASTER,
                    help="fixed master raw for the pad test (default 64); "
                         "lower it if either state clips")
    ap.add_argument("--tests", nargs="+", default=["digital"],
                    choices=sorted(TESTS) + ["all"],
                    help="which tests to run (default: digital)")
    args = ap.parse_args()
    PAD_MASTER = args.pad_master
    GAIN_MASTER = args.gain_master
    GAIN_STEP = args.gain_step
    GAIN_FROM = args.gain_from
    GAIN_TO = args.gain_to

    names = sorted(TESTS) if "all" in args.tests else args.tests
    needs_cable = [n for n in names if TESTS[n][1]]
    if needs_cable and not args.cable:
        sys.exit("these tests need a patched analog loop: %s\n"
                 "re-run with --cable once an output is patched to input 1, "
                 "with PAD on and phantom power OFF."
                 % ", ".join(needs_cable))

    dev = Dev(args.card)
    print("bbf-measure v%s, card %s, %s"
          % (VERSION, args.card,
             "analog loop patched" if args.cable else "no cable"))
    if args.cable:
        print("phantom power state (check this is off before trusting it):")
        for n in PHANTOM_NUMIDS:
            line = [l.strip() for l in
                    subprocess.run(["amixer", "-c", args.card, "cget",
                                    "numid=%d" % n],
                                   capture_output=True, text=True
                                   ).stdout.splitlines()
                    if l.strip().startswith(": values")]
            print("   numid=%d %s" % (n, line[0] if line else "?"))

    try:
        for n in names:
            TESTS[n][0](dev)
    except KeyboardInterrupt:
        print("\ninterrupted")
    finally:
        print("\nrestoring: gain 0, loopback off, master %d" % MASTER_SAFE)
        dev.restore()


if __name__ == "__main__":
    main()
