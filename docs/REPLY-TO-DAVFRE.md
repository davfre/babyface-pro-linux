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

Merged, thanks! And thanks for digging into the why instead of just throwing a patch at me, that's what made it quick to check.

Your diagnosis is spot on. The DMA addresses were sitting in `chip->dma_in[]` / `chip->dma_out[]` doing nothing except getting freed again at teardown, which is pretty clearly me forgetting a step rather than deciding anything. I went and looked at the neighbours: every driver in `sound/usb` that uses `usb_alloc_coherent` sets the flag the way you do here (`endpoint.c`, `midi.c`, `midi2.c`, `misc/ua101.c`). Mine was the only one that didn't.

Slightly alarming side effect: the RFC series I currently have sitting on linux-sound has this bug in it. So if a maintainer had actually plugged a Babyface in and tried it, it just wouldn't have worked. Good timing on your part. It goes into v4.

Sorry for merging before writing back, that auto-closed #1 on you with no explanation. Not the first impression I wanted to give someone's first contribution here.

---

## Issue #1 — stream never starts with an IOMMU

Closed automatically when #3 got merged. Sorry about that, the commit had a `Fixes #1` trailer and I pushed before writing anything back to you.

Fix is in `main`, details are on #3.

---

## PR #2 — mic gain encoding

Merged. I wanted to check this one myself before believing it, and honestly the result is a bit embarrassing for me, because the proof was already sitting in my own repo.

`PROTOCOL.md` says bits 5-7 are a transaction counter, and it quotes five captured wValues as the evidence: `0x2A, 0x0A, 0x49, 0x29, 0x09`. Decode those with your encoding and you get **31, 30, 29, 28, 27 dB**. That's just someone dragging a knob down one dB at a time. So I ran the same decode over all of `ctlout_gain_solo.txt` (59 distinct writes on mic 1) and got a completely normal fader drag out of it: 31 down to 8, back up, down to 0, up to 7, down to 0, with **57 of 58 steps being exactly 1 dB**. The one exception is a skipped dB during a fast drag. That capture is from an FS, so the encoding is the same on both models.

I also ran your no-cable sweep here on the FS, Mic 2, nothing plugged in, phantom off:

| | before | after |
|---|---|---|
| distinct hardware states (16 requested) | 7 | 15 |
| least-squares slope from 38 dB | 0.808 dB/dB | **1.000 dB/dB** |
| mean step | +0.74 dB | +0.94 dB |
| worst step | **−0.99 dB** | +0.40 dB |

Yours gave 1.001 on the non-FS, mine gives 1.000.

The "worst step" row is the bit I hadn't picked up from your write-up. Those negative steps are the rotating value landing in the fine-gain bits, so asking for **+1 dB could actually make it quieter**, and setting the same value twice didn't even give the same gain. That's a lot worse than just losing resolution.

PROTOCOL.md is fixed. I kept the old wrong explanation in place marked as superseded rather than deleting it, so it's clear how it went wrong. That also explains the old sweep that reported "~2 dB per step, clamps at raw 23": it was walking the packed byte instead of a linear gain index.

The part that stings a bit is that the same note already said the raw→dB anchor had never actually been measured, and that settling it would need a Windows capture with known dB values. That capture was already in the repo. Thanks for being the one to go and look.

---

## Issue #4 — non-FS unit, measurements and notes

This is great, thank you. Honestly a second unit, a different model and a repeatable way to measure things is worth more to this driver than the two patches on their own. Going through your points in order.

**Descriptors.** I can answer this one straight away. My FS reports:

```
idVendor 2a39   idProduct 3fc0   bcdDevice 0001
iProduct "Babyface Pro (73055480)"
```

Same `bcdDevice` as yours, same `iProduct` shape, and this bit surprised me: **my FS doesn't say "FS" anywhere either**. So as far as I can tell the two models are simply indistinguishable from the descriptors. Which unfortunately kills the clean version of your idea, since pulling the card name from `iProduct` would give both units `Babyface Pro (<serial>)`, serial number and all.

Your actual point stands though, and I've acted on it.

**Card naming, changed.** `card->driver` is `BabyfacePro` now, shortname `Babyface Pro`. Your unit should stop announcing itself as an FS. While testing that I ran into something you couldn't have known about: ALSA derives the card *id* from the last word of the shortname, so it was `hw:FS` before and turned into `hw:Pro` after the rename. Both useless. I'm deriving it caiaq-style now and it comes out `hw:BabyfacePro`.

**Unity on every load, changed.** You were right, and it's a bit worse than you described: the default routes all 14 sources into every output at 0 dB each, so they **sum**, and that runs on every fresh module load, before alsa-restore gets a chance to put the user's levels back. Masters now come up at **−20 dB**, the figure you suggested. I used the exact 8-bit/16-bit register pair the hardware's own DIM button writes, so at least it's a value the device already uses rather than one I made up. Routing default is unchanged, so the card still makes sound with nothing in user space.

One side effect you'll probably notice: DIM is an **absolute** −20 dB, so with the new default it doesn't do anything audible until you push a master above that. That's always been true of the hardware, it's just obvious from the first second now.

**DIM, it works now.** Same host-in-the-loop arrangement as SET, which already toggled phantom from the same poll, so there wasn't really a principle being defended by leaving DIM inert. The README was overclaiming and I've fixed that too. Tested with the actual button: two presses, two `Dim Switch` events, two `Front Panel Dim` events, toggles back and forth cleanly, nothing in dmesg.

One thing from that test doesn't match what you saw, and I'd rather say so than quietly go along with it. You wrote that pressing DIM "changes `Front Panel Button` and nothing else". Over here the press moves **`Front Panel Dim`**, and `Front Panel Button` didn't move at all. Doesn't affect the fix and I haven't chased it, but if you were watching `Front Panel Button` to decide the button did nothing, that might be why. If it's a real difference between the two units that's more interesting than me miscapturing, so worth a look if you're ever in there.

**Control naming, you're right, and I've left it alone on purpose.** Especially that indices 2 and 3 are Hi-Z instrument inputs called "Mic" running 0-9 dB instead of 0-65. The crosspoints already name themselves per source so there's a pattern to copy. The only reason I haven't done it is that renaming ALSA controls breaks anything matching the old names, so I'd rather do it in one pass with any other naming change than dribble it out.

**What would help most.** Yes please to the scripts and the raw output, especially the measurement harness. I'd also like to mention the non-FS result in the next RFC round. Reviewers were always going to ask how many units this has ever run on, and until today the honest answer was "one". Say the word if you'd rather I didn't.

On credit: your two commits keep your authorship, and I'll carry them into the kernel submission under your own `Signed-off-by` rather than folding them into mine. Let me know what name and email you want on them.
