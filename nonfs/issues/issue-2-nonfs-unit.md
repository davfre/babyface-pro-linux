**Title:** Works unmodified on a non-FS Babyface Pro — plus a gain-law measurement that doesn't match `bf_gain_db()`

---

Following on from the DMA issue — here's what the rest of the testing on
the 2015 (non-FS) Babyface Pro turned up. Short version: it all works, and
one calibration constant looks like it may be off for both models rather
than just mine.

## It's the same device to the driver

The older unit enumerates identically to the FS: `2a39:3fb0` class
compliant, `2a39:3fc0` proprietary, and in proprietary mode interface 5,
`ep 0x01 OUT` / `0x82 IN`, altsettings 1/2/3 carrying 448/640/1024-byte
packets — exactly what the driver expects. With the DMA fix it binds and
streams with no other changes, full-duplex 48 kHz S32_LE, mixer controls
all present.

Since both models share `2a39:3fc0` there's no way to tell them apart by
ID. My unit's `iProduct` reads `Babyface Pro (70784522)` — if an FS says
something different there, that string would be the discriminator, and
would double as a display name. `bcdDevice` is `0.01` here, also worth
comparing. Might be worth checking what yours reports, even if only to
know whether a distinction is possible.

Minor, related: the card, its name and its PCM all say "Babyface Pro FS",
so on the older unit `aplay -l`, PipeWire and every DAW picker show a
model that isn't plugged in. `snd-usb-audio` handles this neatly in class
compliant mode by taking the name from `iProduct`. Since `card->driver` is
what alsa-lib and UCM match on, it's easier changed before merge than
after.

## The digital master law is exact

Measured through the device's own Loopback, `AN1/2 Playback Volume` from
raw 16384 down to 256: expected tracked measured with **0.00 dB spread**
across the full 36 dB span, reproduced three times. `raw = 8192 *
2**(dB/6)` is spot on. Everything purely digital seems to port across
models unchanged.

## Mic gain measures ~2.97 dB per register step, not 3.25

Two independent methods, agreeing:

**Without any cable.** Sweep the gain with nothing patched and measure the
noise floor — the preamp amplifies its own input noise, so above the ADC
floor the measured level tracks real gain. Least-squares over raw 12–20
(where preamp noise dominates): **2.968 dB/step**.

```
   raw   db set   measured      step        raw   db set   measured      step
     0        0    -113.80                   11       35     -92.15     +1.55
     1        2    -113.52     +0.28         12       38     -89.34     +2.81
     2        5    -111.76     +1.76         13       41     -86.64     +2.71
     3        9    -111.71     +0.05         14       44     -83.73     +2.90
     4       12    -109.40     +2.32         15       48     -80.60     +3.13
     5       15    -106.35     +3.05         16       51     -77.65     +2.95
     6       18    -103.57     +2.78         17       54     -74.76     +2.89
     7       22    -100.33     +3.24         18       57     -71.59     +3.18
     8       25     -97.61     +2.72         19       61     -68.68     +2.91
     9       28     -94.81     +2.80         20       64     -65.82     +2.86
    10       31     -93.70     +1.11
```

**Through an analog loop** (AN1/2 out → input 1, PAD on, phantom off),
one point per register step: **2.972 dB/step** over raw 0–15.

The two rigs are valid over complementary ranges — the noise method is
swamped by the ADC floor at low gain, the cable rig compresses at the top
— and they agree where each is valid, 2.968 against 2.972, sharing no
signal path.

That puts the span at roughly **59.4 dB across raw 0–20, against the 65 dB
in `bf_gain_db()`** — about 5.6 dB optimistic at the top.

Every register step produces a clean, distinct, monotonic change, so the
21-step grid and the dB→register mapping are right; it's only the scale.

### Probably not a model difference

I checked RME's specs before assuming my older unit explains it, and they
don't support that. Both models are published with the same gain figures —
the [Babyface Pro page](https://babyface.rme-audio.de/) says "a gain range
of 76 dB, adjustable in steps of 1 dB", the [FS
page](https://rme-audio.de/babyface-pro-fs.html) says "−11 dB up to
+65 dB" in "steps of 1 dB". What RME *do* document as different is mic SNR
(112.2 → 113.7 dB), line-input THD (8 dB better), and the FS's added
+19/+4 dBu output switch. None of those move a gain law by 0.3 dB/step.

So I'd guess the constant is approximate for both, not that my preamps
differ from yours. The no-cable noise sweep takes two minutes and needs no
cable at all — if you run it on the FS we'd know either way.

### Related: the 1 dB step question in CALIBRATION.md

You note there that TotalMix shows 1 dB steps while only 21 raw levels
exist, and conclude the display must round. RME's spec says 1 dB for both
models, so either that's right or there's a fine-gain register still
undecoded — 21 values can't express 1 dB steps over 65 dB.

One data point for your current reading: if `0x20`/`0x40` were high bits
of a wider gain value rather than a transaction counter, the sweep would
have jumped around as `gain_cycle` rotated through them. It was monotonic
across all 21 steps.

## PAD is ~10.3 dB, constant, and survives reloads

Measured by A/B at a fixed operating point: **10.29, 10.27, 10.22 dB** at
low level, flat. Consistent with the −11 dB bottom of RME's published
range.

It initially looked gain-dependent (falling to 7 dB at high gain), but
that's the measurement, not the PAD: two runs 18 dB apart line up to
0.04 dB when aligned by *level* rather than by gain. The preamp input
stage compresses as the level into it rises, so removing 10 dB of
attenuation stops buying 10 dB of output. Same effect explains a
full-scale square wave I saw when the master crossed a threshold with PAD
off — the input stage running out of headroom, i.e. exactly what the relay
is there to prevent.

Also: PAD state persists across module reloads. Pre- and post-reload runs
were identical to 0.01 dB, which couldn't happen if cold-init reset it —
so the `0x17 wIdx=0x0000` comment in the source looks correct.

## One provisional number

The 8-bit master register measured 0.427–0.490 dB/code rather than a flat
0.5, and non-uniform. But that was measured through the cable rig at
levels where it compresses, so I'd treat it as provisional until
re-measured properly. Your own `CALIBRATION.md` derives 0.486 and rounds
to 0.5, so there may be something there, but I don't want to claim it on
data I now distrust.

## Minor: control naming

The four preamp gains are all `Mic 1 Capture Volume` with index 0..3, and
both PAD switches are `Pad Mic 1` with index 0/1 — so the index doesn't
mean what the name says, and index 2/3 are the Hi-Z instrument inputs with
a different range and law entirely. Distinct names would read better in
`amixer`/`alsamixer`.

## Method

Scripts and raw output for all of the above are available if useful —
happy to share them or re-run anything on this unit. The no-cable noise
sweep is the one worth reproducing: no cable, no output stage, no loop
linearity to argue about, and nothing to wire up wrong.

Tested on CachyOS, 7.2.4-1-cachyos, x86_64, driver at `bff0263` plus the
DMA fix.
