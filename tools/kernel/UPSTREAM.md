# Upstream submission — snd-usb-babyface-pro

This driver implements the **proprietary mode** of the RME Babyface Pro
FS (VID `0x2a39`, PID `0x3fc0`).  In that mode the PCM stream runs on
INTERRUPT endpoints (interface 5, ep 0x01 OUT / 0x82 IN) instead of the
class-compliant isochronous path, so `snd-usb-audio` cannot handle it
and the driver is standalone, modeled on `snd-usb-caiaq`.

## What is hardware-validated (2026-08, on a real unit)

- Interrupt-endpoint PCM: full-duplex 2 ch S32_LE (24 msbits), 9 rates
  32-192 kHz (3 bandwidth alts), zero xruns in sweeps and soaks
  (period >= 32 frames; 16 with nurbs=16, monitoring-grade).
- Vendor-request mixer (all decoded from Windows USB captures,
  `tools/usbdump/PROTOCOL.md`):
  - 6 output masters + mutes (the 8-bit register is the real volume,
    0.5 dB/step; the 16-bit is a kept-in-sync companion),
  - 4 mic preamp gains (0–65 dB, 1 dB steps, packed coarse/fine
    register — corrected 2026-09-13, see PROTOCOL.md) + 48V/PAD per mic
    (relay clicks and front-panel LEDs verified),
  - 84 crosspoints (6 outputs × 14 sources) on the two maps
    (standard + low),
  - pitch/varispeed (−5%…+5%, 16.8 fixed-point DDS quads),
  - loopback (30-channel 0x15 map), AN1>2, AN1/2 link, MS processor,
    width, FX send, DIM (−20 dB absolute on Phones),
  - front-panel poll (0x17 readback → read-only ALSA controls:
    buttons, wheel, IN/OUT selection, MIX, DIM).
- Re-probe resilience: full mixer cache restored across unbind/rebind
  and across S3 suspend/resume (the firmware has no mixer readback).
- Regression suite `tools/kernel/regress.sh`: 40/40 (rate sweep with
  signal tap, start/stop stress, mixer-restore, mid-stream disconnect).

## Files (as submitted, all checkpatch-clean)

Live under `sound/usb/babyfacepro/` (a subdirectory, NOT flat files
directly in `sound/usb/` — corrected 2026-08-28 after actually
building the integration: this matches the snd-usb-caiaq convention,
and every other vendor-specific USB sound driver in current
linux-next is a subdirectory too, e.g. `6fire/`, `bcd2000/`, `caiaq/`,
`hiface/`, `line6/`. `babyfacepro.c` calls 8 functions defined in
`babyfacepro-ctl.c` directly from `probe()`, so the two files can
only ever be built/linked together — this also killed any hope of a
clean file-boundary patch split, see item 1 below).

- `babyfacepro.c` — core driver: vendor requests + cold init,
  interrupt-URB PCM streaming, mixer-state persistence across
  re-probes/resume, card lifecycle (probe/disconnect/PM/module entry)
- `babyfacepro-ctl.c` — ALSA control surface: mixer (masters, preamp,
  gains, crosspoints, flags, pitch, loopback…), front-panel readback
  poll + controls, hardware DSP EQ
- `babyfacepro.h` — shared state + register map
- `Makefile` — `snd-usb-babyface-pro-y := babyfacepro.o
  babyfacepro-ctl.o` + `obj-$(CONFIG_SND_USB_BABYFACE_PRO) +=
  snd-usb-babyface-pro.o` (copy of `sound/usb/caiaq/Makefile`'s
  pattern)

## Integration diff (kernel tree)

`sound/usb/Makefile` — add `babyfacepro/` to the subdirectory list:

```make
obj-$(CONFIG_SND) += misc/ usx2y/ caiaq/ 6fire/ hiface/ bcd2000/ qcom/ babyfacepro/
```

`sound/usb/Kconfig` — add before `source "sound/usb/line6/Kconfig"`
(`config SND_USB_BABYFACE_PRO`, tristate, selects SND_PCM).

`MAINTAINERS` entry (added alphabetically, before `RNBD BLOCK
DRIVERS`):

```text
RME BABYFACE PRO FS DRIVER (PROPRIETARY MODE)
M:	Ismaïl Bahloul <i.bahloul01@gmail.com>
L:	alsa-devel@alsa-project.org (moderated for non-subscribers)
S:	Maintained
F:	sound/usb/babyfacepro/
```

The RFC patch series (`git format-patch` output of exactly this
diff, built and verified against a real linux-next checkout — see item
7 below) lives at `patches/000[1-4]-*.patch`.  It is a 4-patch series:
core+PCM, mixer, front panel, DSP EQ — each patch builds in-tree (the
control surface is stubbed in patch 1 so the module links at every
step).

## Before sending (reviewer will ask)

1. ~~**Squash to a small patch series** (probe/stream, controls, panel,~~
   ~~state persistence) with one driver per `sound/usb/babyfacepro.c` —~~
   ~~the split into 6 files is for development; upstream sound drivers~~
   ~~are usually single-file or two-file.~~ DONE 2026-08-28, but as ONE
   patch, not a series: squashed to two files — `babyfacepro.c`
   (core: protocol/pcm/state/lifecycle) + `babyfacepro-ctl.c` (ALSA
   controls: mixer/panel/eq) — build, `sparse`/`W=1`/`checkpatch`
   clean, live-tested on the physical unit. A file-boundary patch
   series (patch 1 = babyfacepro.c, patch 2 = babyfacepro-ctl.c) was
   considered and rejected: `babyfacepro.c` calls 8 functions defined
   in `babyfacepro-ctl.c` straight from `probe()`, so patch 1 alone
   wouldn't link — the only way to make that bisectable would be
   throwaway stub functions in patch 1, which is worse than one clean
   patch. This also matches common practice for a wholesale new-driver
   addition (nothing to bisect in code that doesn't exist yet). See
   the RFC patch at `patches/0001-...patch`.
   REVISED 2026-09-01 after Takashi's review note that splitting would
   help review: re-submitted as a **4-patch series** (core+PCM / mixer /
   front panel / DSP EQ). Because the two files are cross-coupled, the
   earlier patches carry stub control-surface functions (replaced by
   the later patches) so every patch builds in-tree; each patch was
   build-verified against linux-next. See `patches/000[1-4]-*.patch`.
2. **`request_firmware`?** No — the device needs no firmware upload;
   the cold init is a fixed vendor-request burst (documented).
3. **Suspend/resume + autosuspend**: S3 verified. USB autosuspend was
   untested and nothing paused the panel poll/keepalive for it, so
   DONE 2026-08-28: explicitly disabled with `usb_disable_autosuspend()`
   at probe (balanced with `usb_enable_autosuspend()` at disconnect) —
   live-tested, `power/control` reads back `on`, clean dmesg. This is
   the safe interim: full autosuspend support (pausing the panel poll/
   keepalive and pairing `usb_autopm_get/put_interface` around the
   stream) is a deliberate follow-up, not implemented/tested this
   round — say so explicitly in the cover letter rather than shipping
   an untested code path.
4. ~~**The panel poll** runs at 50 Hz continuously (vendor reads).  If~~
   ~~reviewers object to always-on polling, gate it on the card having a~~
   ~~control file open or make the interval a module param.~~
   DONE 2026-08-28: `panel_poll_ms` module param (10-1000 ms, 20 =
   default/unchanged), live-tested (loaded at 50 ms, panel controls
   still read correctly, no dmesg errors). Still always-on regardless
   of whether a control file is open — only the interval is tunable,
   not gated on usage — flag this if a reviewer wants the stronger
   fix.
5. **Open protocol items** (documented in PROTOCOL.md, not blockers):
   the preamp readback byte0 index semantics (0x003F vs 0x0000), the
   width strip-ownership tail (cap_width7 family), and the EQ HF warp.
   (The ref-level 3-state map was FULLY DECODED 2026-08-26 — see
   LINUX-VALIDATION.md. It is now exposed as the `Instrument Ref Level`
   enum too, added 2026-09-06 — this note used to say "just isn't
   exposed as a control", which went stale that day.)
6. **Device naming**: the module/card name is `Babyface Pro FS`
   (the FS suffix matters — the non-FS unit has a different PID).
7. **linux-next compile test + get_maintainer.pl** — DONE 2026-08-28,
   **RE-RUN 2026-08-29 with a full in-tree object build**: shallow-cloned
   linux-next (20260828 snapshot), wired `sound/usb/babyfacepro/` into
   `sound/usb/Makefile` + `Kconfig` + `MAINTAINERS`, and compiled the
   two objects in-tree (`make sound/usb/babyfacepro/`), which the
   2026-08-28 `make modules_prepare`+`KBUILD_MODPOST_WARN=1` run did
   NOT do. That in-tree gcc build caught two real linkage bugs the
   clang-only out-of-tree build had silently missed:
   - a stray `extern const struct snd_pcm_ops babyface_pcm_ops;` left
     in `babyfacepro.h` from the 6-file split (its only user is
     `babyfacepro.c`, where the ops are `static`) → removed;
   - `bf_apply_masters()` left `static` in `babyfacepro-ctl.c` though
     `babyfacepro.c` calls it cross-file (and it's declared in the
     header) → un-static'ed. `split_driver.py` already un-staticked it,
     so the squash had drifted from the split.
   After those two fixes the in-tree build is clean (no warnings even
   with `CONFIG_WERROR=y` from the snapshot's defconfig) and the patch
   was re-generated from linux-next. Also ran linux-next's own (newer)
   `checkpatch.pl --strict`, which surfaced 34 CHECK-level style nits
   `selftests.sh`
   silently misses (it only grep-filters for ERROR|WARNING, not CHECK) —
   fixed 30 of them (alignment-to-open-paren, stray blank lines, a
   chained assignment, a line ending in `(`); left 4 as deliberate
   false positives: `bInterfaceNumber` (CamelCase — it's usb.h's own
   struct field, not renameable), `(1 << 27)` → `BIT()` (declined —
   `BIT()` returns `unsigned long`, risky in this file's signed
   `s32`/`s64` Q27 fixed-point math), and `ang` "misspelled" ×2 (a
   real CORDIC angle variable, not a typo — this is literally the
   same false "fix" that `checkpatch --fix-inplace` silently applied
   when first tried, which is also why `--fix-inplace` output was
   discarded wholesale rather than trusted: it also changed
   `(1 << 27)` to `BIT()` unprompted).
   `get_maintainer.pl -f` (run from the linux-next tree with the new
   files copied to their target `sound/usb/` paths) →
   Jaroslav Kysela <perex@perex.cz>, Takashi Iwai <tiwai@suse.com>,
   linux-sound@vger.kernel.org, linux-kernel@vger.kernel.org. Re-run
   before actually mailing — MAINTAINERS entries can change.

## v4 (not sent yet - what has accumulated since v3)

v3 went out 2026-09-02 (4 patches + cover letter, archived on
lore/linux-sound). No reviewer reply as of 2026-09-13. Meanwhile the
tree has moved ahead of what is on the list, so a v4 is owed
regardless of whether a review arrives:

- **Two real bugs fixed by an outside contributor, David Fredman**
  (PRs #2 and #3, merged 2026-09-13). Both are present in the v3
  series as mailed, so v4 is not optional:
  - **The stream URBs never handed the HCD their existing DMA
    mapping.** The buffers come from `usb_alloc_coherent()` but were
    submitted without `URB_NO_TRANSFER_DMA_MAP`, so the USB core tried
    to map them a second time and failed with `-EAGAIN` on any
    IOMMU-translated host - the default on current AMD and Intel
    desktops. **v3 as submitted does not stream at all on such a
    machine.** Every other `sound/usb` driver that allocates coherent
    buffers sets the flag (`endpoint.c`, `midi.c`, `midi2.c`,
    `misc/ua101.c`); this one was the exception.
  - **The mic gain register was decoded wrongly.** Bits 5-7 are the
    fine part of the gain, not a transaction counter; the driver
    masked them off and wrote a rotating value into them. Result: 21
    of 66 positions reachable, and the gain actually applied depended
    on where the rotation stood - up to 2 dB of non-determinism for
    the same requested setting. Verified against this repo's own FS
    capture and re-measured on the FS unit (1.000 dB/dB after, 0.808
    before). See PROTOCOL.md's corrected gain section.
- **A second tester on a second hardware model.** Fredman runs the
  driver unmodified on an original (2015, non-FS) Babyface Pro: same
  VID:PID, same descriptors. This answers the bus-factor question
  reviewers were expected to raise (old item 3 below), and it is worth
  saying in the v4 cover letter. Note the two models cannot be told
  apart from the descriptors: the FS here reports `bcdDevice` 0.01 and
  `iProduct` "Babyface Pro (73055480)" - no "FS" anywhere - which is
  also what the non-FS reports.
- **Open design questions raised by that report**, none of them fixed
  here because they are judgement calls, not defects:
  - `card->driver` is hardcoded to `"BabyfaceProFS"`, and that string
    is what alsa-lib config and UCM profiles match on. Easy to change
    now, impossible after a kernel merge.
  - `babyface_write_default_mixer()` routes all 14 sources into every
    output at 0 dB with masters at 0 dB on every fresh load. That
    sums. On monitors with no volume control of their own it is a
    real hazard at first plug-in, before alsa-restore runs.
  - All four gains are named `Mic 1 Capture Volume` (index 0-3),
    though index 2 and 3 are Hi-Z instrument inputs running 0-9 dB.
    Same for `Pad Mic 1`. Naming them per input, as the crosspoints
    already do with AN1/AN2, would read better.
- **5 new controls** (2026-09-06, `c72cfaf` + `77dcf1a`): Sample Clock
  Source, Instrument Ref Level, Phase Switch, Stereo Split Switch,
  Input Trim. None of these have ever been posted for review.
- **Input Trim restore bug** found and fixed 2026-09-13 (odd channel of
  a pair replayed the wrong value on the wire after a re-probe) - see
  KERNEL-DRIVER.md known-gap 3 for the hardware trace.
- **dB TLV** added on crosspoints / preamp gains / trims 2026-09-13
  (previously only the 6 masters had any).
- **The regression suite was unrunnable from 2026-09-01 to 2026-09-13**
  (the S24_LE -> S32_LE switch never reached the test tooling). Fixed,
  and the suite re-run on the current code: **40 pass / 0 fail**
  (2026-09-13). Until then the "40/40" claim in the cover letters was
  inherited from before the S32_LE change - worth keeping in mind if a
  reviewer asks what exactly was validated on which revision.
- **Style regressions in the post-v3 code cleaned up** 2026-09-13:
  2 non-ASCII characters had crept back into comments (Takashi asked
  for plain ASCII in the v2 review), plus 13 alignment CHECKs and one
  over-long line. Back to the 4 known checkpatch --strict false
  positives; sparse C=2 and W=1 clean.

Two things to fix in the v4 cover letter itself:

- The v3 cover contradicts itself: the changelog announces the S24_LE
  -> S32_LE switch, then the "What's included" block a few lines down
  still says S24_LE. Fixed in the repo by `d4ac3bf`, never on the list.
- It needs a proper v3 -> v4 changelog listing the 5 new controls, so
  a reviewer coming to v4 cold isn't surprised by unreviewed code.

Regeneration prerequisite: `~/DATA/05_Code/linux-next-src` is stale -
it still sits on the single-patch v1 commit (2026-08-29, linux-next
20260828) and its copies of `sound/usb/babyfacepro/*.c` no longer match
this repo. Pull a fresh linux-next, re-copy the sources, rebuild
in-tree, then `git format-patch` the series again.

## Cover letter

The mailing cover letter (0/N email, separate from the 1/N patch) is
`patches/COVER-LETTER.md` — includes the known-limitations block
(autosuspend, open protocol items, load-time latency profile) that the
`Before sending` items below ask to state explicitly.

## Follow-ups (post-merge)

- **Dynamic buffer reconfiguration**: switch the latency profile (e.g.
  256-sample default ↔ 16-frame low-latency floor) **at runtime** like
  the Windows Fireface USB Settings panel, instead of the current
  load-time-only module params (`frames_per_urb`/`nurbs`, read once in
  `probe()`; today switching means a reload/rebind).  See
  `KERNEL-DRIVER.md` Known-gaps item 15 for the design sketch. Kept
  out of the RFC on purpose: it touches the streaming core and is not a
  submission blocker.

## Build / test commands

```sh
# out-of-tree build (CachyOS clang kernel)
make LLVM=1 -C /lib/modules/$(uname -r)/build M=$PWD modules

# non-regression suite (needs the card, no other client holding it)
sh tools/kernel/regress.sh --dur 1 --mixer-restore --disconnect-test

# style
/lib/modules/$(uname -r)/build/scripts/checkpatch.pl --no-tree --file <file>
```
