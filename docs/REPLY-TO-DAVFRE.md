# Replies to David Fredman (PRs #2, #3, issues #1, #4)

**Posted 2026-09-13.** Kept here as the record of what was said and why;
the live copies are the GitHub comments linked below.

- PR #3: https://github.com/ismail-bahloul/babyface-pro-linux/pull/3#issuecomment-5655066902
- Issue #1: https://github.com/ismail-bahloul/babyface-pro-linux/issues/1#issuecomment-5655067064
- PR #2: https://github.com/ismail-bahloul/babyface-pro-linux/pull/2#issuecomment-5655067884
- Issue #4: https://github.com/ismail-bahloul/babyface-pro-linux/issues/4#issuecomment-5655068975

Note for next time: the merge commit for #3 carried a `Fixes #1` trailer,
so pushing auto-closed his issue before anything had been written back to
him. Merge and reply should go out together, or the reply first.

---

## PR #3 — DMA mapping

Merged, thank you — and thank you for diagnosing it rather than just patching it, that is what made it quick to confirm.

You are right about the cause. The coherent DMA addresses were being tracked in `chip->dma_in[]` / `chip->dma_out[]` and then never used for anything except `usb_free_coherent()` at teardown, which is the shape of an omission rather than a decision. For what it is worth, every other driver under `sound/usb` that allocates coherent buffers sets the flag the way you do here — `endpoint.c`, `midi.c`, `midi2.c`, `misc/ua101.c` — so this one was the odd one out.

This matters more than a local bug report. The RFC series currently sitting on linux-sound has the defect, which means it would not have streamed on most modern desktops if a reviewer had tried it. It goes into v4.

Sorry for merging before writing back — that also auto-closed #1 on you with no explanation. Not how I meant to handle a first contribution.

---

## Issue #1 — stream never starts with an IOMMU

Closed automatically by the merge of #3 — apologies for the silent close, the push carried the `Fixes #1` trailer before I had written anything back to you.

The fix is in `main`. The reasoning and the in-tree precedent are in the comment on #3.

---

## PR #2 — mic gain encoding

Merged. I checked this one rather than taking it on trust, and the result is worth writing down, because the evidence was already sitting in my own tree.

`PROTOCOL.md` documented bits 5-7 as a transaction counter and quoted five captured wValues as the proof: `0x2A, 0x0A, 0x49, 0x29, 0x09`. Under your encoding those decode to **31, 30, 29, 28, 27 dB** — a knob being dragged down one dB at a time. Running the same decode over the whole of `ctlout_gain_solo.txt` (59 distinct writes on mic 1) gives a clean human fader drag — 31 down to 8, back up, down to 0, up to 7, down to 0 — with **57 of 58 transitions being exactly 1 dB**, the single exception a skipped dB during a fast drag. That capture is from an FS, so the encoding is the same on both models.

I also ran your no-cable sweep here, on an FS, Mic 2 with nothing connected and phantom off, measuring the preamp noise floor from 35 to 50 dB:

| | before | after |
|---|---|---|
| distinct hardware states (16 requested) | 7 | 15 |
| least-squares slope from 38 dB | 0.808 dB/dB | **1.000 dB/dB** |
| mean step | +0.74 dB | +0.94 dB |
| worst step | **−0.99 dB** | +0.40 dB |

Your non-FS gave 1.001, this FS gives 1.000.

The worst-step row is the part I had not appreciated from your write-up: those negative steps are the rotating value landing in the fine-gain bits, so asking for **+1 dB could move the gain down**, and the same requested setting did not even give a repeatable gain. That is a good deal worse than the resolution loss.

`PROTOCOL.md` is corrected, with the old reading kept and marked superseded rather than deleted, so the record of how it came to be wrong stays readable. The old sweep note that reported "~2 dB per step, clamps at raw 23" is explained too: it was walking the packed byte rather than a linear gain index.

One thing I owe you: that same note already said the absolute raw→dB anchor had never been measured and that a Windows capture with known dB values was needed. The capture was in the tree the whole time. Thank you for actually looking.

---

## Issue #4 — non-FS unit, measurements and notes

Thank you for this — a second unit, a second model and a repeatable measurement method are worth more to this driver than the two patches on their own. Taking your points in order.

**The descriptors.** I can answer this one directly. My FS reports:

```
idVendor 2a39   idProduct 3fc0   bcdDevice 0001
iProduct "Babyface Pro (73055480)"
```

Same `bcdDevice` 0.01 as yours, same `iProduct` shape — and note my **FS does not say "FS" anywhere either**. So the two models look indistinguishable from the descriptors, which kills the neat version of your suggestion: taking the card name from `iProduct` would name both units `Babyface Pro (<serial>)`, serial number and all.

It does not make the underlying point wrong, though, and I have acted on it.

**Card naming — changed, before it can freeze.** `card->driver` is now `BabyfacePro`, shortname `Babyface Pro`. Your unit should stop announcing itself as an FS. While testing that I hit something you could not have seen: the card *id* is derived by the core from the last word of the shortname, so it was `hw:FS` before and became `hw:Pro` after the rename — both useless. It is derived caiaq-style now, whitespace stripped from the shortname, and reads `hw:BabyfacePro`.

**Unity on every load — changed.** You were right, and it was slightly worse than you put it: the default routes all 14 sources into every output at 0 dB each, so they **sum**, on every fresh load, before alsa-restore can put the user's levels back. Masters now come up at **−20 dB**, your suggested figure. I used the exact 8-bit/16-bit register pair the hardware's own DIM button writes, so it is a measured value rather than one I picked. The routing default is unchanged, so the card still makes sound with nothing in user space.

One consequence worth knowing: DIM applies an **absolute** −20 dB, so with the new default it does nothing audible until a master is raised above that. That is how the hardware has always behaved; it is just visible from the first second now.

**DIM — it acts now.** Same host-in-the-loop arrangement as SET, which already toggled phantom from the same poll, so there was no principle being upheld by leaving DIM inert. The README was overclaiming and is corrected. Tested with the physical button: two presses give two `Dim Switch` events and two `Front Panel Dim` events, clean toggle round-trip, nothing in dmesg.

One detail from that capture does not match your description, and I would rather flag it than quietly repeat it. You wrote that pressing DIM "changes `Front Panel Button` and nothing else". Here the press moves **`Front Panel Dim`**, and `Front Panel Button` did not move at all in the capture. It makes no difference to the fix, and I have not chased it — but if you were watching `Front Panel Button` to decide the button was inert, that may be why. A real difference between the two units would be more interesting than a miscapture on my side, so it is worth a glance if you are ever looking.

**Control naming — agreed, and deliberately still open.** Particularly that indices 2 and 3 are Hi-Z instrument inputs called "Mic", running 0-9 dB rather than 0-65. The crosspoints already name themselves per source, so there is a pattern to follow. I have left it alone for now only because renaming ALSA controls breaks anything matching the current names, so I would rather decide it in one pass together with any other naming change than piecemeal.

**What would help most.** Yes to the scripts and the raw output, please, especially the measurement harness. I would also like to cite the non-FS result in the next RFC round — reviewers were always going to ask how many units this had ever run on, and "one" was the honest answer until today. Tell me if you would rather I did not.

On attribution: your two commits keep your authorship, and I will carry them into the kernel submission under your own `Signed-off-by` rather than folding them into mine. Tell me which name and address you want on them.
