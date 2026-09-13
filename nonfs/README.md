# Testing snd-usb-babyface-pro on a non-FS Babyface Pro

## What this is

[snd-usb-babyface-pro](https://github.com/ismail-bahloul/babyface-pro-linux)
is a Linux kernel driver for the RME Babyface Pro FS. It was written by
reverse engineering Windows USB captures, and it is currently under review
on the linux-sound mailing list as an RFC patch series.

The hardware here is an **original Babyface Pro from 2015, not the FS**.
RME refreshed the product in 2019: better converters, a femtosecond clock,
an added output level switch. The question was whether the driver works on
the older unit, and whether the numbers it was calibrated with still hold
there.

Everything in this folder came out of one session on 2026-09-13. CachyOS,
kernel 7.2.4-1-cachyos, x86_64, AMD, driver at commit `bff0263`.

## Background you need to read the rest

The Babyface Pro has two USB personalities. In **class compliant mode** it
enumerates as a standard audio device and the stock `snd-usb-audio` driver
handles it, with a limited channel count and no access to the internal
mixer. In **proprietary mode** the PCM stream runs on interrupt endpoints
instead of the usual isochronous ones, and the mixer is driven by vendor
specific control requests. `snd-usb-audio` cannot touch that mode at all,
which is why a separate driver exists. You switch between them by holding
SELECT and DIM while plugging in power.

Two facts shape everything below.

The firmware has **no mixer readback**. The driver can write a fader value
but never read one. So the driver keeps its own cache of what it believes
it wrote, and `amixer` shows you that cache, not the hardware.

All the mixer values are **register codes, not decibels**. The driver
converts between the two using constants it derived from the Windows
captures. Those constants are what we set out to check.

## The bug

On this machine the driver would not stream at all. It probed, registered a
card, and then failed every stream start with `-EAGAIN`, about 86 times a
second for as long as anything kept retrying.

The cause is a DMA mapping error. The driver allocates its stream buffers
with `usb_alloc_coherent()`, which returns memory that is already mapped for
the device, and keeps the mapping handles. But it submits the URBs without
setting `transfer_dma` or the `URB_NO_TRANSFER_DMA_MAP` flag, so the USB
core tries to map the buffers a second time with `dma_map_single()`.

When the IOMMU runs in translated mode, which is the default on current AMD
and Intel desktops, a coherent allocation can be a vmap rather than
contiguous low memory, and the second mapping fails. On a machine where the
allocation happens to be contiguous, the same code works by accident.

The fix is four lines, in `patches/0001-fix-urb-dma-mapping.patch`. With it
applied the stream starts first time. Everything else here was measured
with that patch in place.

## The measurements

Each section says what the test checks, then whether the result matches
what the driver assumes and what RME publish.

### Does the older unit look like an FS over USB?

**Yes, exactly.** Same vendor and product IDs in both modes, `2a39:3fb0`
class compliant and `2a39:3fc0` proprietary.

The rest applies to proprietary mode, the one this driver handles. Same
interface 5, same interrupt endpoints `0x01 OUT` and `0x82 IN`, same three
altsettings carrying 448, 640 and 1024 byte packets. The driver binds and
streams with no changes to the ID table or anything else.

Class compliant mode looks different, as it should: four interfaces rather
than six, and isochronous streaming on interfaces 1 and 2.

One consequence worth noting: the two models cannot be told apart by USB
ID. If their calibration ever does differ, the driver has no way to pick.
The `iProduct` string might serve, since this unit reports `Babyface Pro
(NNNNNNNN)`, the digits being the unit's own number, and an FS may say
something else. Full descriptors in
`results/probe-cc.txt` and `results/probe-pc.txt`.

### Digital output master law

The output master fader is applied in the firmware's DSP, before any
converter. The driver assumes `raw = 8192 * 2^(dB/6)`, so halving the
register value drops the level by 6 dB.

You can test this without any cable, because the device can loop its own
output back into its capture channels digitally.

**Matches.** Zero spread across a 36 dB span, repeated three times.
Numbers in `results/2026-09-13-digital-masterlaw.txt`.

### Mic preamp gain law

This is the analog one. The control is in decibels, 0 to 65, and the driver
converts to a 5 bit register with `raw = (db * 8 + 13) / 26`. That gives 21
distinct register values, which the driver treats as 3.25 dB apart, adding
up to 65 dB across the range.

RME publish the same figures for both models: a 76 dB range, meaning -11 to
+65 dB, in 1 dB steps.

**Differs.** Each register step is worth about 2.97 dB on this unit, not
3.25, so the range spans roughly 59 dB rather than 65. The driver overstates
gain by about 5.6 dB at the top.

Two independent methods agree:

| method | signal path | valid over | result |
|---|---|---|---|
| preamp noise floor, no cable | none, the preamp amplifies its own noise | raw 12 to 20 | 2.968 dB/step |
| analog loop, cable patched | DAC, XLR out, cable, preamp, ADC | raw 0 to 15 | 2.972 dB/step |

Each method is only valid over part of the range. The noise measurement needs
enough gain to sit above the converter's own noise floor. The loop measurement
needs levels below where it starts compressing, for reasons explained under
"what the measurements taught us" below. They overlap nowhere but agree to
0.004 dB/step.

The register grid itself is correct. Every step produces a clean, distinct,
monotonic change, at exactly the control values the driver's rounding
predicts. Only the scale is wrong.

Full tables in `results/2026-09-13-noise-gainlaw.txt` and
`results/2026-09-13-cable-gainlaw.txt`.

### Is this a difference between the two models?

Probably not. RME document the two units as differing in mic signal to
noise ratio, 112.2 against 113.7 dB, in line input distortion, 8 dB better,
and in the FS gaining a +19/+4 dBu output switch. None of those changes a
gain law by 0.3 dB per step, and the published gain figures are identical.

So the constant is more likely approximate for both models than specific to
this one. Running the no cable test on an FS would settle it, and takes two
minutes.

### PAD

PAD is a relay that attenuates the microphone input to protect it from line
level signals. The driver models it as a plain switch and makes no claim
about its depth. RME imply 11 dB, as the bottom of the published -11 to +65
dB range.

**Matches, at about 10.3 dB.** Constant across the gain range once you
measure it correctly. Numbers in `results/2026-09-13-pad-ab.txt` and
`results/2026-09-13-pad-vs-gain.txt`.

PAD state also survives a module reload, which means the driver's cold init
does not disturb it.

### 8 bit output master register

The calibration notes in the driver's repo identify an 8 bit register as
the real analog output volume, with the 16 bit one acting as a shadow, and
treat it as 0.5 dB per code.

**Provisional, appears to differ.** We measured 0.427 to 0.490 dB per code,
and not uniform across the range. But that measurement went through the
analog loop at levels where it compresses, so the number may be an artifact.
It is the one figure here that should not be quoted until it is redone at
lower levels.

For context, the repo's own calibration file derives 0.486 dB per code and
rounds it to 0.5, so there may be something real underneath.

## What the measurements taught us

The analog loop, output patched back into an input, compresses when the
level arriving at the preamp input is high. Not when the preamp output
is high, which is the intuitive assumption and the wrong one.

That single fact explained three separate results that each looked like a
hardware finding:

The gain sweep appeared to taper over its top five register steps. The no
cable method is cleanest in exactly that region and shows no taper.

PAD depth appeared to shrink from 10.2 dB to 7 dB as gain rose. Two runs
18 dB apart line up to within 0.04 dB when you align them by level instead
of by gain, so it was never about gain.

With PAD off, raising the master by 6 dB once produced a 22 dB jump into a
full scale square wave. That is the input stage running out of headroom,
which is the overload PAD exists to prevent.

The practical rule: the analog loop is trustworthy only while the preamp
input is low. The no cable method has no input signal at all and is immune,
which is why it is the one to publish and the one to ask others to
reproduce.

## Running the tests yourself

`bbf-probe.sh` dumps USB descriptors, ALSA state and kernel messages. Run
it once in each mode.

`bbf-measure.py` runs the measurements. Two of them need no cable:

    ./bbf-measure.py --tests digital
    ./bbf-measure.py --tests noise

The rest need an analog output patched to input 1, and refuse to start
without `--cable`:

    ./bbf-measure.py --cable --tests linearity gain pad padsweep

Gain and master are restored when it exits, including on Ctrl-C.

## Safety

Check phantom power is **off before** patching anything. 48 V into a line
output is the only combination here that can damage hardware. Set PAD on
before connecting, not after.

Remember that `amixer` shows the driver's cache, not the hardware.

The driver applies a factory default on load: every source routed to every
output, all masters at 0 dB, unmuted. It does this because it has no saved
scene to restore and no way to read the current state. macOS and Windows
never do this, because TotalMix restores your own workspace. Set your
levels and run `sudo alsactl store`, so udev's alsa-restore puts them back
after each load.

Do not write registers outside the range the driver uses. An attempt to
probe gain register values above the driver's clamp produced nothing
interpretable and was abandoned.

## Open questions

Whether an FS measures 2.97 dB per step too. This decides whether the fix
is one corrected constant or a per model calibration.

Whether the 8 bit master law really deviates, once remeasured at levels
where the loop is linear.

Whether `iProduct` or `bcdDevice` differ between the models, which decides
whether per model behaviour is even possible.

## Contents

    bbf-measure.py      measurement tool
    bbf-probe.sh        descriptor and state dump
    results/            raw output of every run, with conditions recorded
    issues/             drafts written up for the upstream repo
    patches/            the DMA fix, plus one test only patch
    archive/            earlier scripts, kept because numbers were quoted
                        from them before they were superseded
