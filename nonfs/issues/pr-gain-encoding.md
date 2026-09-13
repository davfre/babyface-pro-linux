<!-- gh pr create --title "ALSA: usb: babyface-pro: fix the mic gain encoding (1 dB steps, full 65 dB range)" -->

The mic gain control currently reaches 21 hardware states, about 3 dB apart,
across its 0 to 65 dB range. The hardware does 1 dB steps. This packs the
value the way TotalMix does, which restores the resolution and the top of the
range.

## What was wrong

`bf_gain_put()` wrote

```c
(raw & 0x1f) | counter
```

with `counter` rotating through 0x20, 0x00, 0x40 on each write, on the reading
that bits 5-7 are a transaction counter.

They are not a counter. They are the low part of the gain value. USBPcap
captures of TotalMix on Windows show:

```
coarse = min(dB / 3, 20)     bits 0-4, 3 dB per step
fine   = dB - 3 * coarse     bits 5-7, the 0-2 dB remainder
wValue = (fine << 5) | coarse
```

Above 60 dB `coarse` saturates at 20 and `fine` continues 3, 4, 5, so 65 dB is
`0xb4`. Verified against 48 gain writes across four captures, every value
matching.

So the driver was masking off the fine part of every setting and then writing a
rotating value into those same bits, which also meant the gain depended on
where the rotation happened to be.

`bf_gain_db()` had the matching error, treating each register step as 3.25 dB.
Measured, the coarse step is 3.00 dB.

The Hi-Z inputs were already right: their value is gain in 0.5 dB units, which
is what `db * 2` produces. Captures confirm 1 dB -> `0x02`, 9 dB -> `0x12`,
and 4.5 dB -> `0x09`.

## Measured before and after

Same unit, same script, same 35 to 50 dB sweep, only the driver differing. No
cable: gain is swept with nothing patched and the preamp's own noise floor is
measured, which above about 33 dB tracks real gain directly and has no large
signal in it to compress.

Before, three or four dB values collapse onto one hardware state:

```
 db set     measured       step
     38       -89.45
     39       -89.58      -0.13
     40       -89.60      -0.02
     41       -86.65      +2.95
     42       -86.66      -0.01
     43       -86.63      +0.03
     44       -83.72      +2.91
     45       -83.75      -0.03
     46       -83.76      -0.01
     47       -83.71      +0.05
     48       -80.58      +3.12
     49       -80.60      -0.01
     50       -80.56      +0.04
```

After, every dB moves the hardware:

```
 db set     measured       step
     35       -91.74
     36       -90.50      +1.24
     37       -89.60      +0.90
     38       -88.61      +0.99
     39       -87.66      +0.95
     40       -86.67      +0.99
     41       -85.67      +0.99
     42       -84.75      +0.92
     43       -83.70      +1.05
     44       -82.74      +0.96
     45       -81.59      +1.16
     46       -80.59      +1.00
     47       -79.56      +1.03
     48       -78.67      +0.89
     49       -77.65      +1.02
     50       -76.61      +1.04
```

Least squares over that range: **1.001 dB per dB of control**, mean step 1.009,
span 15.13 dB across 15 dB. Fitting from 38 or 40 instead gives 1.004 and
1.010.

Cross-check on the same hardware from the other side: running RME's own driver
and setting gain in TotalMix on macOS, measured gain tracks the label at
**0.999 dB per labelled dB** across 0 to 40 dB. So 1 dB per dB is what the
vendor's software gets, and now what this driver gets.

## Notes

`gain_cycle` is removed, since nothing needs a counter now. That also drops it
from the saved state struct.

Tested on an original Babyface Pro (2015, not the FS), CachyOS, kernel
7.2.4-1-cachyos, x86_64. The driver otherwise runs unmodified on that unit;
same USB IDs, same descriptors.

Captures, notes and the measurement scripts are available if useful. The no
cable sweep above is two minutes to reproduce on an FS and needs nothing
patched, which would confirm the encoding is the same on both models.
