// SPDX-License-Identifier: GPL-2.0-only
/*
 * RME Babyface Pro FS - proprietary-mode USB audio driver
 *
 * Level meters.  The device has no meter readback (the vendor
 * software computes its meters on the host from the stream), so the
 * driver measures the samples as they pass through the URB completion
 * handlers and exposes the result as read-only controls:
 *
 *   "Capture Meter Peak"     largest |sample| per capture channel
 *   "Capture Meter RMS"      RMS per capture channel
 *   "Capture Meter Overs"    longest run of full-scale samples
 *   "Playback Meter Peak"    the same for the playback channels
 *   "Playback Meter RMS"
 *   "Playback Meter Overs"
 *
 * Each value covers the interval since the previous read of that
 * control: a read returns the accumulated value and starts a new
 * interval.  That lets a mixer application polling at a display rate
 * see every peak, which a snapshot could miss between polls.  The
 * controls are therefore VOLATILE, and more than one reader will see
 * split intervals.
 *
 * Channel order follows the PCM channel order of the matching
 * direction (capture 0-11, playback 0-11).  Levels are 24-bit
 * magnitudes, 0 to 0x7fffff (0 dBFS).  The meters only move while the
 * stream runs, i.e. while some application has a substream running;
 * otherwise every read returns zero.
 *
 * The capture meters run on every IN URB, whether or not a capture
 * substream is open, so input levels show while only playback runs.
 * The playback meters measure the OUT URB as sent, so they read
 * silence when no playback substream is open.
 */
#include <linux/bits.h>
#include <linux/kernel.h>
#include <linux/math.h>
#include <linux/math64.h>
#include <linux/spinlock.h>
#include <linux/unaligned.h>
#include <linux/usb.h>
#include <sound/control.h>
#include <sound/core.h>

#include "babyfacepro.h"

/* Full scale of a 24-bit sample; -0x800000 is clamped to this too. */
#define BF_METER_FULL_SCALE	0x7fffff

/* sum_sq accumulates (|s| >> BF_METER_SQ_SHIFT)^2, at most 2^38 per
 * frame.  Halving sum and count past BF_METER_MAX_FRAMES keeps the
 * mean and leaves u64 headroom when nobody reads for minutes.
 */
#define BF_METER_SQ_SHIFT	4
#define BF_METER_MAX_FRAMES	BIT(24)

/* Longest over run reported; plenty for a "N consecutive samples" test. */
#define BF_METER_OVERS_MAX	0xffff

enum bf_meter_kind {
	BF_METER_PEAK,
	BF_METER_RMS,
	BF_METER_OVERS,
};

/* Capture PCM channel -> device word; see babyface_capture_copy(). */
const u8 bf_capture_word_map[BF_METER_CHANNELS] = {
	0, 1, 2, 3, 6, 7, 8, 9, 10, 11, 12, 13
};

static void bf_meter_add(struct bf_meter *m, const u8 *data,
			 unsigned int frames, unsigned int words,
			 const u8 *map)
{
	unsigned int f, ch;

	for (f = 0; f < frames; f++) {
		const u8 *frame = data + f * words * 4;

		for (ch = 0; ch < BF_METER_CHANNELS; ch++) {
			unsigned int wi = map ? map[ch] : ch;
			s32 s;
			u32 a, q;

			if (wi >= words)
				break;
			/* 24-bit sample in bits 31-8 of the word. */
			s = (s32)get_unaligned_le32(frame + wi * 4) >> 8;
			a = min_t(u32, abs(s), BF_METER_FULL_SCALE);

			if (a > m->peak[ch])
				m->peak[ch] = a;
			q = a >> BF_METER_SQ_SHIFT;
			m->sum_sq[ch] += (u64)q * q;
			if (a == BF_METER_FULL_SCALE) {
				if (m->run[ch] < BF_METER_OVERS_MAX)
					m->run[ch]++;
				if (m->run[ch] > m->overs[ch])
					m->overs[ch] = m->run[ch];
			} else {
				m->run[ch] = 0;
			}
		}
	}

	m->frames += frames;
	if (m->frames >= BF_METER_MAX_FRAMES) {
		for (ch = 0; ch < BF_METER_CHANNELS; ch++)
			m->sum_sq[ch] >>= 1;
		m->frames >>= 1;
	}
}

/**
 * bf_meter_capture - measure one IN URB
 * @chip: the device
 * @data: the URB transfer buffer
 * @frames: whole frames in @data
 *
 * Called from the IN completion handler, before the capture copy.
 */
void bf_meter_capture(struct snd_usb_babyface *chip, const u8 *data,
		      unsigned int frames)
{
	unsigned long flags;

	spin_lock_irqsave(&chip->meter_lock, flags);
	bf_meter_add(&chip->meter[SNDRV_PCM_STREAM_CAPTURE], data, frames,
		     chip->frame_bytes / 4, bf_capture_word_map);
	spin_unlock_irqrestore(&chip->meter_lock, flags);
}

/**
 * bf_meter_playback - measure one OUT URB
 * @chip: the device
 * @data: the URB transfer buffer, already filled
 * @frames: frames in @data
 *
 * Playback channel n is device word n, so no map is needed.
 */
void bf_meter_playback(struct snd_usb_babyface *chip, const u8 *data,
		       unsigned int frames)
{
	unsigned long flags;

	spin_lock_irqsave(&chip->meter_lock, flags);
	bf_meter_add(&chip->meter[SNDRV_PCM_STREAM_PLAYBACK], data, frames,
		     chip->frame_bytes / 4, NULL);
	spin_unlock_irqrestore(&chip->meter_lock, flags);
}

static int bf_meter_info(struct snd_kcontrol *kctl,
			 struct snd_ctl_elem_info *uinfo)
{
	uinfo->type = SNDRV_CTL_ELEM_TYPE_INTEGER;
	uinfo->count = BF_METER_CHANNELS;
	uinfo->value.integer.min = 0;
	uinfo->value.integer.max =
		(kctl->private_value & 0xff) == BF_METER_OVERS ?
		BF_METER_OVERS_MAX : BF_METER_FULL_SCALE;
	uinfo->value.integer.step = 1;
	return 0;
}

/* Reading a meter returns the interval's value and starts a new one. */
static int bf_meter_get(struct snd_kcontrol *kctl,
			struct snd_ctl_elem_value *ucontrol)
{
	struct snd_usb_babyface *chip = snd_kcontrol_chip(kctl);
	enum bf_meter_kind kind = kctl->private_value & 0xff;
	int dir = kctl->private_value >> 8;
	struct bf_meter *m = &chip->meter[dir];
	u64 sum_sq[BF_METER_CHANNELS];
	unsigned long flags;
	u32 frames = 0;
	int ch;

	spin_lock_irqsave(&chip->meter_lock, flags);
	switch (kind) {
	case BF_METER_PEAK:
		for (ch = 0; ch < BF_METER_CHANNELS; ch++) {
			ucontrol->value.integer.value[ch] = m->peak[ch];
			m->peak[ch] = 0;
		}
		break;
	case BF_METER_RMS:
		memcpy(sum_sq, m->sum_sq, sizeof(sum_sq));
		frames = m->frames;
		memset(m->sum_sq, 0, sizeof(m->sum_sq));
		m->frames = 0;
		break;
	case BF_METER_OVERS:
		for (ch = 0; ch < BF_METER_CHANNELS; ch++) {
			ucontrol->value.integer.value[ch] = m->overs[ch];
			m->overs[ch] = 0;
		}
		break;
	}
	spin_unlock_irqrestore(&chip->meter_lock, flags);

	/* The square root is done outside the lock. */
	if (kind == BF_METER_RMS) {
		for (ch = 0; ch < BF_METER_CHANNELS; ch++) {
			u64 mean = frames ? div_u64(sum_sq[ch], frames) : 0;
			u32 rms = (u32)int_sqrt64(mean) << BF_METER_SQ_SHIFT;

			ucontrol->value.integer.value[ch] =
				min_t(u32, rms, BF_METER_FULL_SCALE);
		}
	}
	return 0;
}

int babyface_create_meters(struct snd_usb_babyface *chip)
{
	static const char * const names[2][3] = {
		[SNDRV_PCM_STREAM_PLAYBACK] = {
			[BF_METER_PEAK] = "Playback Meter Peak",
			[BF_METER_RMS] = "Playback Meter RMS",
			[BF_METER_OVERS] = "Playback Meter Overs",
		},
		[SNDRV_PCM_STREAM_CAPTURE] = {
			[BF_METER_PEAK] = "Capture Meter Peak",
			[BF_METER_RMS] = "Capture Meter RMS",
			[BF_METER_OVERS] = "Capture Meter Overs",
		},
	};
	unsigned int dir, kind;
	int err;

	for (dir = 0; dir < 2; dir++) {
		for (kind = 0; kind < ARRAY_SIZE(names[0]); kind++) {
			struct snd_kcontrol_new tmpl = {
				.iface = SNDRV_CTL_ELEM_IFACE_PCM,
				.name = names[dir][kind],
				.access = SNDRV_CTL_ELEM_ACCESS_READ |
					  SNDRV_CTL_ELEM_ACCESS_VOLATILE,
				.info = bf_meter_info,
				.get = bf_meter_get,
				.private_value = (dir << 8) | kind,
			};

			err = snd_ctl_add(chip->card,
					  snd_ctl_new1(&tmpl, chip));
			if (err < 0)
				return err;
		}
	}
	return 0;
}
