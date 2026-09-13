# How these measurements were made

Written down so anyone can repeat them, on either model, and so the traps
we fell into are documented rather than rediscovered.

## What we are measuring, and why it is awkward

The Babyface Pro holds its mixer in firmware and will not tell you what any
register currently contains. So you cannot ask the device what a fader is
set to. You can only write a value and then measure what comes out.

Every mixer value is a register code. The driver converts codes to decibels
with constants derived from Windows USB captures. Checking those constants
means measuring real levels.

## Three ways to get a signal back, and what each is good for

**Digital loopback.** The device can route its own output back into its
capture channels inside the firmware, with `Loopback Switch`. No cable, and
no converters involved. Use it for anything applied in the DSP: the output
master law, crosspoints, mutes. Not useful for anything analog.

**Preamp noise floor.** With nothing connected, the preamp amplifies its
own input noise, so the captured noise level tracks gain. No cable, no
output stage, no assumptions about linearity. It is the best method for the
mic gain law, and the easiest for someone else to repeat. It only works
where preamp noise dominates over the converter's own floor, which on this
hardware is roughly the top half of the gain range.

**Analog loop.** Patch an output back to an input with a cable. This is the
only way to measure anything involving the converters end to end, and it is
the one with traps. See below.

**PortAudio, on Windows or macOS.** The same measurement against RME's own
driver and TotalMix, which tells you what the vendor's software actually
does rather than what the Linux driver thinks it does. This is how we found
that TotalMix's gain labels are accurate to 1 dB.

## The trap that cost us three false findings

The analog loop compresses when the level arriving at the **preamp input**
is high. Not when the preamp output is high, which is the intuitive
assumption.

So a measurement can look perfectly linear while the preamp output is loud,
as long as the input is quiet, and can compress while everything downstream
looks modest. Three results looked like hardware findings until this was
understood:

- The mic gain sweep appeared to taper over its top five register steps.
  The noise method, which is cleanest exactly there, shows no taper.
- PAD depth appeared to shrink from 10.2 dB to 7 dB as gain rose. Two runs
  18 dB apart line up to 0.04 dB when aligned by level rather than by gain.
- Raising the output master by 6 dB once produced a 22 dB jump into a full
  scale square wave. That was the input stage running out of headroom.

**Always run the linearity control first.** Freeze every device control and
vary only the digital amplitude of the tone. Nothing on the device changes,
so the slope you get is the loop's own. If it is not 1.000, no law measured
through that loop means anything.

## Measuring levels without fooling yourself

Use RMS over a settled window, not peak, and skip the first second of each
capture.

Watch peak separately, and discard any point above about 0.9. A clipped
point is not a quiet version of the truth, it is a square wave, and
averaging it in produces confident nonsense. Our PAD depth read 28 dB that
way, against a real 10.3.

At the quiet end, remember the noise floor adds in quadrature. A curve that
flattens as level falls is usually `sqrt(S^2 + N^2)` rather than a
compressing device. Fit `N` and check before concluding anything: ours fit
every point to 0.01 dB with a single value.

Level-set at the **loudest** configuration you intend to measure. If you
autolevel with PAD on and then switch it off, you clip.

Do not fit through points you know are invalid. Fit each method only over
the range where it is valid, and prefer two methods that agree over one
with more points.

## Safety

Phantom power is the only thing here that can damage hardware. 48 V into a
line output is the combination to avoid. Check it is off **before**
connecting a cable, not after, and note that `amixer` shows the driver's
cache rather than the hardware.

PAD on before connecting. A line level output into a mic preamp overloads
it without PAD, which is what the relay exists to prevent.

The driver writes every source into every output at unity on load. Set your
levels before anything is plugged in, and keep monitors off and headphones
away from your head until you have seen a sane reading.

Do not write registers outside the range the driver uses. Values above the
driver's gain clamp produced nothing interpretable and were abandoned.

## Tools here

    bbf-probe.sh                 USB descriptors, ALSA state, kernel messages
    bbf-measure.py               the Linux measurements, all modes
    bbf-level.py                 one reading, or a repeating readout, for
                                 when something else changes the gain
    bbf-gaincheck-portaudio.py   the same gain question on Windows or macOS,
                                 against TotalMix
    bbf-latency-sweep.py         xruns against period size, any ALSA device

`bbf-measure.py --tests digital noise` needs no cable. Everything else
requires `--cable` and refuses to run without it.
