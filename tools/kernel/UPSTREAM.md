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
- `babyfacepro-meter.c` — level meters: peak/RMS/over accumulators fed
  from the URB completion handlers, read through read-only volatile PCM
  controls (drain on read)
- `babyfacepro.h` — shared state + register map
- `Makefile` — `snd-usb-babyface-pro-y := babyfacepro.o
  babyfacepro-ctl.o babyfacepro-meter.o` + `obj-$(CONFIG_SND_USB_BABYFACE_PRO) +=
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

The current RFC series is `patches/v4-000[0-3]-*.patch`, three patches
plus a cover letter, generated against next-20260911 — see the "v4"
section below for how it is cut and why. `patches/v3-*` is kept beside
it as the record of what was actually mailed on 2026-09-02.

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

## v4 - SENT 2026-09-14

Mailed via `git send-email` to linux-sound@vger.kernel.org, Cc
linux-usb@vger.kernel.org, alsa-devel@alsa-project.org, Jaroslav
Kysela, Takashi Iwai, linux-kernel@vger.kernel.org. All 4 messages
(cover letter + 3 patches) accepted by Gmail's SMTP server
(`Result: 250` on each). `git send-email` auto-CC'd David Fredman on
patch 1 specifically, detected from his `Co-developed-by:`/
`Signed-off-by:` trailers in that patch's body.

Pre-send checklist, all confirmed on the generated patch files (not
just the sources) immediately before sending:
- Every point from Takashi's v2 review that required a code change is
  present in v4 (Reported-by/Closes removed, stream-model big-picture
  section, SPDX in the Makefile, ASCII-only comments, `BF_CTL_TIMEOUT`,
  `BF_CROSS_L/R_FIRST/LAST`, `bf_vendor_write_cycle()`, S32_LE with
  msbits, the playback-clamp comment rewritten). The one non-code point
  (the alsactl-restore design question) was already answered by email
  in the v3 round and didn't need repeating.
- checkpatch --strict: 0 errors on all 3 patches, only the 2 known
  `ang` false positives on patch 3.
- `get_maintainer.pl`, re-run fresh: Jaroslav, Takashi, David (via his
  trailers), the sound lists — no stray recipients.
- Zero `FILL-IN-BEFORE-SENDING` placeholders left.
- Zero non-ASCII characters in any added line, aside from "Ismaïl" in
  Signed-off-by/MODULE_AUTHOR/MAINTAINERS lines.
- The cover letter body read in full, by eye, confirming plain English
  throughout.

Now waiting on review. Track replies via lore.kernel.org (behind an
Anubis bot-check that blocks direct fetches - use the ratatoskr.run
mirror, `ratatoskr.run/linux-sound/<yyyy>/<mm>/<id>/t`, found via
search) or the recipients' own replies landing in the sender's inbox.

## v4 - RE-CUT AGAIN 2026-09-14 (DCO resolved, -20dB scope narrowed) - READY TO SEND, pending explicit go-ahead

**The DCO blocker is gone.** David Fredman provided his real identity
on issue #4: `David Fredman <davfre@gmail.com>`. Patch 1's
`Co-developed-by:`/`Signed-off-by:` no longer carry
`FILL-IN-BEFORE-SENDING` - checkpatch --strict on the generated patch
now reports 0 errors (down from the 2 deliberate ones), and
`get_maintainer.pl` lists David by name. This was the one remaining
blocker; nothing else is holding the series back now.

**A second, smaller fix went in alongside the DCO substitution.**
David also flagged (issue #4, same session as his DCO reply) that the
blanket -20 dB power-on default from the previous re-cut reached the
four digital outputs (AS1/2, ADAT3/4, ADAT5/6, ADAT7/8) too, where
there is no hazard to mitigate - narrowed to the two analog outputs
(AN1/2, PH3/4) only; the digital ones keep the vendor software's 0 dB
default. See KERNEL-DRIVER.md's "Power-on defaults" section for the
full reasoning and the hardware verification.

**Verification note for next time**: chasing the scope-fix's
apparent non-effect on hardware cost real time before it turned out
to be the already-documented `alsactl restore` trap (a stale
system-wide `asound.state`, cached from before this exact change
existed, silently overwriting the driver's correct fresh defaults
about two seconds after every probe) rather than a bug in the fix
itself. Confirmed via `dev_info` tracing at three points (the
per-output write loop, the end of `babyface_write_default_mixer`, and
inside `bf_master_get` itself) that the driver's own computation and
cache were correct throughout, and the divergence appeared only
between the function returning and the control being queried -
exactly the window `alsactl restore` fires in. `sudo alsactl store`
resolved it; re-verified against both a resynced state file and a
genuinely fresh one (no prior entry for this card at all, simulating
a first-time install). Same lesson as the 2026-09-07 phantom-power
incident and this session's earlier crosspoint-restore test:
**any power-on-default or restore check needs a synced `alsactl`
state first, checked explicitly, not assumed** - a stale system file
looks exactly like a driver bug and will burn time on the wrong
target if not ruled out first.

**DIM's scope was investigated too, not fixed.** David's other
question (does DIM reach outputs besides Phones on a monitor setup)
turned out to need more than a quick patch: PROTOCOL.md documents
"Main Out" - what DIM actually targets - as a reassignable TotalMix
setting, not a hardware constant, so the single capture we have
(Main Out = Phones) may not be the only possible protocol behaviour.
Guessing a broader scope without a capture showing what a reassigned
Main Out actually writes risks inventing behaviour no evidence
supports. Flagged as an open protocol question in PROTOCOL.md instead
- the real next step is a fresh Windows capture with Main Out
reassigned, not a code change.

## v4 - RE-CUT 2026-09-14 (v3 had a real crosspoint bug), not sent

**A real driver bug was found and fixed 2026-09-14 while trying to
hardware-verify the crosspoint dB TLV added the day before, and it was
present in both v3 (already mailed) and the first cut of v4.** The
AN1/2 output's crosspoint fader had no audible effect on the signal
for any source - a swept tone produced no level change at all, off
through +6 dB, while the identical control targeting any other output
worked correctly. Root cause and fix are in KERNEL-DRIVER.md's
"THE AN1/2 CROSSPOINT BUG" entry and in `bf_xpoint_write()`'s own
comment. This forced a full re-derivation of the v4 patch series
(the fix lives in patch 1's core+mixer scope), documented below.

`patches/v4-000[0-3]-*.patch`, generated against **next-20260911**.
Three patches, not four:

- `[1/3]` core + PCM + the ALSA mixer
- `[2/3]` the front-panel poll and controls
- `[3/3]` the hardware DSP EQ

**Why three and not four.** v3 split the mixer into its own patch,
which forced the earlier patches to carry stub control functions that
later patches replaced. The mixer and the core share
`struct snd_usb_babyface` and the entire save/restore path -
`bf_saved` *is* mixer state - so that seam was artificial and made
review harder, not easier. The panel and the EQ do separate cleanly:
the driver builds with zero warnings without either. **Every patch
here contains only final code; nothing a later patch rewrites.** Each
was built in-tree on its own (`make sound/usb/babyfacepro/` after
checking out that commit), 0 errors and 0 warnings at each step.

**Re-cut lesson (2026-09-14):** deriving patch 1 (core+mixer, no
panel, no EQ) by stripping functions from the full source left dead
code behind twice - a 28-entry CORDIC table plus two EQ text arrays,
and separately a panel enum plus three text arrays - because the
stripping only removed *functions*, not the file-scope `static const`
data those functions used. None of it triggered a compiler warning:
this kernel's default build flags don't warn on unused file-scope
`static const` arrays (`-Wunused-variable` covers locals, not these).
checkpatch didn't catch it either. The only thing that did was a
purpose-built same-file "declared once, used once" scanner. Same class
of gap as the S24_LE test-tooling and the Rust-comment
`get_maintainer.pl` misfires from the day before: automated checks
that pass are not the same as a clean patch, and each of those three
incidents was caught by a different, narrowly-built check because no
single tool covers all of them. Re-running the same scanner against
the *shipped* driver (not just the derived patch) found 7 more orphaned
defines (`BF_WORDS_PER_FRAME`, `BF_REQ_STATUS`, `BF_REQ_SESSION_STOP`,
`BF_REF_LEVEL_MINUS10DBV`, `BF_MASTER_0DB`, `BF_MASTER_8_0DB`,
`BF_MASTER_UNMUTE`) - pre-existing, unrelated to this bug, left alone
for now as a separate, low-priority cleanup rather than scope-creeping
into this fix.

`patches/v4-000[0-3]-*.patch`, generated against **next-20260911**.
Three patches, not four:

- `[1/3]` core + PCM + the ALSA mixer
- `[2/3]` the front-panel poll and controls
- `[3/3]` the hardware DSP EQ

**Why three and not four.** v3 split the mixer into its own patch,
which forced the earlier patches to carry stub control functions that
later patches replaced. The mixer and the core share
`struct snd_usb_babyface` and the entire save/restore path -
`bf_saved` *is* mixer state - so that seam was artificial and made
review harder, not easier. The panel and the EQ do separate cleanly:
the driver builds with zero warnings without either. **Every patch
here contains only final code; nothing a later patch rewrites.** Each
was built in-tree on its own (`make sound/usb/babyfacepro/` after
checking out that commit), 0 errors and 0 warnings at each step.

Verification on the generated patch files, not just the sources:

- checkpatch --strict: `[2/3]` is 0/0/0; `[3/3]` has the two known
  `ang` false positives; `[1/3]` has the one known `BIT()` CHECK plus
  two deliberate ERRORs, see the blocker below.
- **Zero non-ASCII** in any added line (the author's name aside).
  v3 did **not** have this property: `v3-0001` and `v3-0002` shipped 8
  added lines with em dashes and box-drawing characters, in the stub
  glue, after the v3 cover letter told Takashi "Converted all comments
  to plain ASCII". The ASCII pass had been run on the repo sources
  only, and the stub code existed nowhere else - the same shape of
  mistake as the regress.sh S24_LE breakage. Hence: check the
  generated patches, not the sources.
- Two bugs were caught by that verification while cutting v4: a
  `----------------` heading underline in the `[1/3]` commit message
  (`git am` would have truncated the message there, dropping exactly
  the "stream model" explanation Takashi had asked for), and a
  `get_maintainer.pl` run that pulled the whole Rust for Linux team in
  because two comments mentioned the userspace app's Rust
  implementation.

**BLOCKER: the series cannot be sent yet.** `[1/3]` carries
`FILL-IN-BEFORE-SENDING` in David Fredman's `Co-developed-by:` and
`Signed-off-by:`. His GitHub author address is a
`users.noreply.github.com` one, which is not DCO-valid. The
placeholder is deliberate and fail-safe: checkpatch reports it as an
ERROR and `git send-email` cannot parse it as an address, so the
series cannot go out with his credit missing or wrong. He has been
asked for the name and address he wants (issue #4, 2026-09-13).

The integration branch lives at `~/DATA/05_Code/linux-next-src`,
branch `v4b`.

## What went into v4 since v3

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
- **Three design questions from that report, settled 2026-09-13**
  (all three get harder to change once this is in a released kernel):
  - **Card naming is model-neutral.** `card->driver` is `BabyfacePro`,
    shortname `Babyface Pro`, and the card id is derived from the
    shortname with whitespace stripped (caiaq's idiom) rather than
    left to the core, which produced `hw:FS` before and `hw:Pro`
    after the rename. It is `hw:BabyfacePro` now. This matters most
    for `card->driver`, which alsa-lib configs and UCM profiles match
    on.
  - **Power-on masters are -20 dB, not 0 dB.** The default routing
    sums all 14 sources into every output at unity, on every fresh
    load, before alsa-restore can restore the user's levels. The
    failure is asymmetric - too quiet is fixed in a second, too loud
    cannot be taken back. -20 dB is the exact register pair the
    hardware's own DIM writes, so it is a measured value rather than
    an invented one. Consequence worth knowing: DIM is an *absolute*
    -20 dB, so it is inaudible until a master is raised above that.
  - **The front-panel DIM button acts now.** It was decoded and then
    ignored, so the button looked dead with the driver alone while the
    README claimed full panel emulation. SET already toggles phantom
    from the same poll. The write path is factored into
    `bf_dim_apply()`, which asserts the mutex rather than taking it,
    since it is now reached from both the control and the panel work -
    the exact shape that self-deadlocked this driver once before.
    **Verified with the physical button** (2026-09-13): two presses on
    the FS produced two `Dim Switch` change events and two `Front Panel
    Dim` events, the switch returned to off after the second press, and
    dmesg stayed clean. The `Front Panel Dim` movement is the useful
    half of that: it is the device reflecting its own engaged-dim state
    back through the 0x17 readback, so the write really reached the
    wire rather than only the driver's cache.
- **Still open from that report**: all four gains are named
  `Mic 1 Capture Volume` (index 0-3) though index 2 and 3 are Hi-Z
  instrument inputs running 0-9 dB, and both PADs are `Pad Mic 1`.
  Renaming them per input, as the crosspoints already do with
  AN1/AN2, is an ALSA-control-name change that would break anything
  matching the current names, so it wants deciding in one go with any
  other naming change rather than piecemeal.
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

The cover letter is generated with the series and lives at
`patches/v4-0000-cover-letter.patch` — it carries the v3 -> v4
changelog and the known-limitations block (autosuspend, open protocol
items, load-time latency profile) that the `Before sending` items ask
to state explicitly. `patches/COVER-LETTER.md` is the older
hand-written markdown version, kept for its history only.

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

## v5 - RE-SPLIT 2026-09-17 (Takashi's v4 review: still too coarse) - READY, pending explicit go-ahead

Takashi's reply to v4 (2026-09-16): the 3-patch split is still too coarse
to review. Asked for a minimalistic core (probe/disconnect/PCM only, no
mixer), mixers added piece-by-piece, suspend/resume near the end, and
proper "big picture" documentation for human reviewers, not AI.

No functional change from v4 - this is a pure restructuring, verified by
diffing the final cumulative tree against the actual v4 source: identical
function set (modulo the deliberate splits below), +31 lines out of 5583
(explanatory comments only).

8 patches instead of 3, built and `checkpatch --strict` clean individually
against `next-20260911` at every step:

1. Core: probe/disconnect/PCM stream only.
2. Output masters + crosspoint matrix (kept together - a driver with
   masters but no routing would still be silent, since the factory
   default routing this patch also adds is what makes it audible).
3. Mic preamp + phantom/pad/instrument-ref-level + phase/split/trim.
4. Routing flags + varispeed pitch (kept together - the source function
   that created them registered all of them in one pass; splitting pitch
   out alone would have meant an artificial function split).
5. S3 suspend/resume.
6. Front-panel poll + controls.
7. Hardware DSP EQ.
8. New: `Documentation/sound/cards/babyface-pro.rst`, the big-picture doc
   Takashi asked for.

David Fredman's contributed fixes (the DMA flag, the crosspoint low-map
write, the mic gain packed coarse/fine decode) now land in three different
patches (1, 2, 3) instead of the single v4 patch 1 they used to share, so
his `Co-developed-by`/`Signed-off-by` trailers were copied onto all three
rather than just one.

One real, pre-existing gap found and flagged (not fixed - out of scope for
a pure restructuring pass): `babyface_resume()` calls
`babyface_restore_state()` but not `bf_state_apply_flags()`, unlike
`bf_state_restore()` which calls both - so loopback/AN1>2/link/MS/DIM/
width/FX-send/pitch likely don't survive an S3 resume correctly, even
though the masters/crosspoint/preamp state does. Worth a follow-up patch
of its own; not touched here.

No `Assisted-by:` trailers on the individual patches this time (dropped
per instruction) - the general AI-assistance disclosure paragraph stays
in the cover letter only, same as v4's own disclosure.

Patches: `patches/v5-0000-cover-letter.patch` through
`patches/v5-0008-*.patch`. Not sent - same rule as always, explicit
go-ahead required first.
