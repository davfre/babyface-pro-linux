# Draft replies to David Fredman (PRs #2, #3, issues #1, #4)

Not posted — review and send (or adapt) as you see fit.

---

## On PR #3 / issue #1 (DMA mapping)

Merged, thank you — and thank you for the diagnosis rather than just
the patch, it made this quick to confirm.

You are right about the cause. The coherent DMA addresses were being
tracked in `chip->dma_in[]` / `chip->dma_out[]` and then never used for
anything except `usb_free_coherent()` at teardown, which is exactly the
shape of an omission rather than a decision. For what it is worth,
every other driver under `sound/usb` that allocates coherent buffers
sets the flag the same way you do here — `endpoint.c`, `midi.c`,
`midi2.c`, `misc/ua101.c` — so this was the odd one out.

This matters more than a local bug report: the RFC series currently
sitting on linux-sound has this defect, which means it would not stream
on most modern desktops if a reviewer tried it. It goes into v4.

## On PR #2 / the gain encoding

Merged. I checked it rather than taking it on trust, and the result is
worth writing down because the evidence was already in my own tree.

`PROTOCOL.md` documented bits 5-7 as a transaction counter and quoted
five captured wValues as proof: 0x2A, 0x0A, 0x49, 0x29, 0x09. Under
your encoding those decode to 31, 30, 29, 28, 27 dB — a knob being
dragged down one dB at a time. Running the same decode over the whole
of `ctlout_gain_solo.txt` (59 distinct writes on mic 1) gives a clean
human fader drag — 31 down to 8, back up, down to 0, up to 7, down to 0
— with 57 of 58 transitions being exactly 1 dB, the one exception a
skipped dB during a fast drag. That capture is from an FS, so the
encoding is the same on both models.

I also ran your no-cable sweep on the FS, on Mic 2 with nothing
connected and phantom off, measuring the preamp noise floor over 35-50
dB:

| | before | after |
|---|---|---|
| distinct hardware states (16 requested) | 7 | 15 |
| least-squares slope from 38 dB | 0.808 dB/dB | **1.000 dB/dB** |
| mean step | +0.74 dB | +0.94 dB |
| worst step | -0.99 dB | +0.40 dB |

Your non-FS gave 1.001; the FS gives 1.000. The negative steps in the
"before" column are the rotating value landing in the fine-gain bits,
so asking for +1 dB could move the gain down — the same requested
setting did not even give a repeatable gain. That is worse than the
resolution loss and I had not noticed it.

`PROTOCOL.md` is corrected, with the old reading kept and marked as
superseded rather than deleted, so the record of how it was got wrong
stays.

## On the descriptors (issue #4)

I can answer this one directly. My FS reports:

```
idVendor  2a39   idProduct 3fc0   bcdDevice 0001
iProduct  "Babyface Pro (73055480)"
```

So: same `bcdDevice` 0.01 as yours, same `iProduct` shape, and note
that my FS does not say "FS" anywhere either. The two models appear to
be indistinguishable from the descriptors, which kills the neat version
of your suggestion — taking the card name from `iProduct` would name
both units "Babyface Pro (<serial>)", with a serial number inside the
card name.

That does not make the underlying point wrong. `card->driver` is
hardcoded to `"BabyfaceProFS"`, it is what alsa-lib and UCM match on,
and it is effectively frozen once this reaches the kernel. I would
rather fix it now than later. I am inclined toward a model-neutral
`card->driver` with the marketing name left in `shortname`, but I want
to think about what that does to anyone already matching on the current
string.

## On the rest of issue #4

- **Unity on every load** — you were right and it was slightly worse
  than you put it: `babyface_write_default_mixer()` routes all 14
  sources into every output at 0 dB each, with masters at 0 dB, so they
  sum. Changed: masters now come up at **-20 dB**, your suggested
  figure. I used the exact 8-bit/16-bit pair the hardware's own DIM
  button writes, so it is a measured value rather than one I picked.
  The routing default is unchanged, so the card still makes sound with
  nothing in user space. One consequence you may notice: DIM is an
  *absolute* -20 dB, so it now does nothing audible until you raise a
  master above that.
- **DIM decodes but never acts** — fixed, it acts now, same
  host-in-the-loop arrangement as SET. The README was overclaiming and
  is corrected too, and the physical button is tested: two presses on
  the FS give two `Dim Switch` events and two `Front Panel Dim` events,
  with a clean toggle round-trip and nothing in dmesg.

  One detail from that capture does not match your description. You
  wrote that pressing DIM "changes `Front Panel Button` and nothing
  else"; on this unit the press moves **`Front Panel Dim`**, and
  `Front Panel Button` did not move at all in the capture. It makes no
  difference to the fix, and I have not chased it, but if you were
  watching `Front Panel Button` to decide the button was inert, that
  may be why. Worth a glance on the non-FS if you happen to be
  looking — a genuine difference between the two units would be more
  interesting than my miscapture.
- **Card naming** — changed before it can freeze. `card->driver` is
  `BabyfacePro`, shortname `Babyface Pro`, and the card id is now
  derived caiaq-style rather than left to the core, which was giving
  `hw:FS` (and `hw:Pro` after the rename). It reads `hw:BabyfacePro`.
  Your unit should stop announcing itself as an FS.
- **Control naming** — agreed, particularly that indices 2 and 3 are
  Hi-Z instrument inputs called "Mic". The crosspoints already name
  themselves per source, so there is a pattern to follow.

## What would help most

Yes to the scripts and raw output, please — especially the measurement
harness. Having a second unit, a second model and a repeatable
measurement method is worth more to this driver than the two patches
on their own, and I would like to cite the non-FS result in the next
RFC round if you have no objection.

On attribution: your commits keep your authorship, and I will carry
them into the kernel submission with your `Signed-off-by` rather than
folding them into mine. Tell me which name and address you want on
them.
