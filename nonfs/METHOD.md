# How to measure this hardware, and why

The Babyface Pro holds its mixer in firmware and will not report what any
register contains. You cannot ask what a fader is set to, only write a
value and measure what comes out. Every mixer value is a register code,
and the driver converts codes to decibels using constants derived from
USB captures, so checking those constants means measuring real levels.

## The two measurements that matter

Neither needs a cable. Both take about two minutes.

    ./bbf-measure.py --tests digital
    ./bbf-measure.py --tests noise

**Output master law** (`digital`). The device routes its own output back
into its capture channels inside the firmware, via `Loopback Switch`. No
cable, no converters, nothing analog in the path. Good for anything
applied in the DSP: master law, crosspoints, mutes.

**Mic gain law** (`noise`). With nothing connected, the preamp amplifies
its own input noise, so the captured noise level tracks gain directly.
No cable, no output stage, no assumption of linearity. Valid where preamp
noise dominates the converter's own floor, which here is roughly the top
half of the range, so fit from about 35 dB up.

## Why the gain sweep ramps and waits

Changing the gain puts a step at the preamp output, which decays through
the input coupling with a time constant near 1.2 s. A point measured
straight after a change lands in the tail of that and reads too loud.

The decay, visible as a fixed 35 dB setting settles, each residual about
a ninth of the last:

```
      35       -87.21
      35       -91.48      -4.27
      35       -91.94      -0.46
      35       -91.97      -0.02
```

So the script walks the gain 1 dB at a time between points, the finest
the control goes, keeping each transient as small as the hardware allows.
Then it reads until two consecutive measurements agree before recording
one, at every point rather than only the first.

The tolerance sets how much residual survives, near enough one for one:
two reads agree once the remaining error is about 1.1 times the
tolerance. At the 0.25 dB default a 5 dB step can still be 0.3 dB out.
Use `--settle-tol 0.10`, or measure in 1 dB steps.

## Why not a cable

An analog loop is the only way to measure the converters end to end, and
it compresses when the level arriving at the **preamp input** is high.
Not when the preamp output is high, which is the intuitive assumption. So
it can look linear while the output is loud, and compress while
everything downstream looks modest.

If you use one, run the linearity control first: freeze every device
control and vary only the digital amplitude of the tone. Nothing on the
device changes, so the slope is the loop's own. If it is not 1.000,
nothing measured through that loop means anything.

## Reading levels

RMS over a settled window, not peak, and skip the first second of each
capture.

Watch peak separately and discard anything above about 0.9. A clipped
point is not a quiet version of the truth, it is a square wave.

At the quiet end the noise floor adds in quadrature, so a curve that
flattens as level falls is usually `sqrt(S^2 + N^2)` rather than a
compressing device. Fit `N` and check.

Level-set at the loudest configuration you intend to measure. Autolevel
with PAD on, then switch it off, and you clip.

Fit each method only over the range where it is valid, and prefer two
methods that agree over one with more points.

## Safety

Phantom power is the only thing here that can damage hardware. 48 V into
a line output is the combination to avoid. Check it is off **before**
connecting anything, and remember `amixer` shows the driver's cache
rather than the hardware.

PAD on before connecting. A line output into a mic preamp overloads it
without PAD, which is what the relay is for.

Set levels before anything is plugged in, and keep monitors off and
headphones away from your head until you have seen a sane reading.

## Tools

    bbf-probe.sh                 USB descriptors, ALSA state, kernel messages
    bbf-measure.py               the measurements above
    bbf-gaincheck-portaudio.py   the same gain question on Windows or macOS,
                                 against TotalMix
    bbf-latency-sweep.py         xruns against period size, any ALSA device

`--tests digital noise` needs no cable. Everything else requires
`--cable` and refuses to run without it.
