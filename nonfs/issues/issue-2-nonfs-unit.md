<!-- gh issue create --title "Measurements from a non-FS Babyface Pro, and a few smaller things" -->

I spent the morning taking measurements of the non-FS Pro. Here's what I found:

| | |
|---|---|
| ✓ | **16 bit output master law** exact on this unit: 0.00 dB spread over a 36 dB span, through the device's own Loopback, repeated three times |
| ✓ | **PAD** about -10.3 dB, and it survives a module reload |
| ✓ | **32-sample buffers** run clean full duplex, with the DMA fix applied and `frames_per_urb=32 nurbs=8` |
| ✗ | **Mic gain law** the control reaches 21 of its 66 positions |

On the last one: the hardware does 1 dB steps, but the control only reaches 21
positions, about 3 dB apart. I captured what TotalMix writes on Windows, and the
value packs a coarse and a fine field into one byte. The fine part is currently
being overwritten by the rotating counter. That is the other PR, with
measurements either side of the change.

## Smaller things

- **Card name hardcoded to FS.** Understandable, since you wrote it for the FS,
  but it runs happily on the older Pro too, where every device picker then
  names the wrong model. Taking it from `iProduct`, as `snd-usb-audio` does in
  class compliant mode, would read correctly for both. Worth doing before the
  driver reaches the kernel, if it does: `card->driver` is what alsa-lib config
  and UCM profiles match on, so renaming it later would break people's configs.
  On the same subject, the two models share `2a39:3fc0`. This unit reports
  `iProduct` as `Babyface Pro (NNNNNNNN)` and `bcdDevice` as `0.01`. Do you
  know what an FS reports? If either differs, the same string would double as a
  way to tell them apart.

- **Unity on every load.** `babyface_write_default_mixer()` routes every source
  into every output at 0 dB each time the module loads, where the cold-init
  clear leaves silence. I realise that is deliberate, so the card is usable
  without TuxMix, and it is a preference rather than a bug. But full output
  into monitors with no volume control of their own can do real damage, while a
  default that is a little low can simply be turned up. Masters at something
  like -20 dB would still be usable out of the box. Saving levels with `alsactl
  store` helps afterwards, but not the first time you plug the card in, and not
  in the gap before alsa-restore runs.

- **DIM decodes but never acts.** Pressing it changes `Front Panel Button` and
  nothing else, so with the driver alone the button appears dead. I assume that
  is for TuxMix to act on, but it does not match "front panel fully emulated"
  in the README.

- **Control naming.** All four input gains are called `Mic 1 Capture Volume`,
  separated only by index, so `amixer` and `alsamixer` list four controls with
  the same name. Index 2 and 3 are the Hi-Z instrument inputs, which run 0-9 dB
  rather than 0-65, so the name is doubly misleading for those. Both PAD
  switches are `Pad Mic 1` the same way. Naming them per input, as the
  crosspoints already are with `AN1`, `AN2` and so on, would read better.

Happy to share the scripts and the raw output if they are any use. Your
captures show what gets written to the device; these measure what comes out of
it. Neither needs a physical loopback: the master law goes through the device's
own Loopback, and the gain sweep measures the preamp's own noise with nothing
connected. A couple of minutes each, if you want to check the numbers in the
other PR against your own unit.
