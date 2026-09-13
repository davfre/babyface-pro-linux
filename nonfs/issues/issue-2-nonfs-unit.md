**Title:** Mic gain control resolves about 3 dB per step; TotalMix resolves 1 dB on the same hardware

---

Following on from the DMA issue, here is what testing turned up on a 2015
Babyface Pro (not the FS).

What I tested, and what came out:

1. **It works as is on a non-FS unit** - no driver changes, down to 32-sample
   buffers, and the output master law and PAD depth both measure as the driver
   assumes.
2. **Mic preamp gain** - the control reaches 21 of its 66 positions, about 3 dB
   apart, where TotalMix on the same unit resolves 1 dB.
3. Some smaller things, at the end.

## 1. It works as is on a non-FS unit

Same IDs as the FS, `2a39:3fb0` class compliant and `2a39:3fc0` proprietary, and
in proprietary mode the descriptors match what the driver expects down to the
altsetting packet sizes. With the DMA fix it binds and streams unchanged, clean
at a 32-sample buffer (`frames_per_urb=32 nurbs=8`), which class compliant mode
on this unit could not do. Full descriptors if you want them.

Two of the calibration constants check out as well. The 16 bit output master law
is exact, 0.00 dB spread across a 36 dB span measured through the device's own
Loopback and repeated three times. PAD measures about 10.3 dB, constant across
the gain range, consistent with the -11 dB bottom of RME's published range, and
its state survives module reloads.

## 2. Mic preamp gain

`bf_gain_raw()` maps the control's 0 to 65 range onto 21 register values, so only
21 of the 66 positions do anything. Measured through an analog loop, 19, 20 and
21 all settle on the same level to 0.01 dB, since all three become register 6.
Each register step is worth about 2.97 dB, measured two ways that share no
signal path (an analog loop over raw 0-15, and the preamp's own noise floor over
raw 12-20, agreeing to 0.004 dB/step). The control therefore spans roughly 59 dB
rather than 65.

The hardware itself is not the limit. On macOS, driving RME's own driver and
setting gain in TotalMix, measured gain tracked the label at **0.999 dB per
labelled dB across 0 to 40 dB**: ask for 10, get 10. So TotalMix reaches
resolution the driver does not, and RME's "1 dB steps" is literal rather than a
rounded display.

Hence the question, since you have the captures and I do not: do they show more
than 21 distinct values written to `0x1A` at `wIndex 0x0000`, or is gain also
carried somewhere else? The driver has a second family, `BF_REG_PANEL_GAIN` at
`0x000A`, used by the front panel wheel, and writing the same raw value there
appears to give a different gain, though I have not measured that cleanly yet.

If you can point at the right encoding I am happy to write and test the patch
here, and to re-run any of the measurements above.

## 3. Smaller things

- The card, its name and its PCM all say "Babyface Pro FS", so on the older unit
  every device picker shows a model that is not plugged in. `iProduct`
  (`Babyface Pro (NNNNNNNN)` here, the digits being the unit's own number) self-labels correctly on both, which is what
  `snd-usb-audio` uses. Easier changed before merge, since `card->driver` is what
  alsa-lib and UCM match on.
- `babyface_write_default_mixer()` puts every source into every output at unity
  on every load. With monitors connected that only has to be wrong once.
  `alsactl store` covers it, but a quieter default would be safer.
- DIM decodes into `Front Panel Button` and nothing acts on it, so the button
  looks dead on the hardware. The README's "front panel fully emulated" reads as
  though it should dim.
- The four preamp gains are all named `Mic 1 Capture Volume`, index 0..3, and
  index 2/3 are the Hi-Z inputs, which have a different range and law.

## Measured on

CachyOS, kernel 7.2.4-1-cachyos, x86_64, AMD, driver at `bff0263` plus the DMA
fix. Raw output of every run is available if it is useful.
