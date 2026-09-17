// SPDX-License-Identifier: GPL-2.0-only
/* meter_selftest.c - userspace check of babyfacepro-meter.c.
 *
 * Unlike the other selftests this compiles the driver's own file, not a
 * copy, against the stubs below.  The kernel headers it includes must
 * resolve to empty files, so build it from a scratch directory (what
 * selftests.sh does):
 *
 *	d=$(mktemp -d); mkdir "$d/linux" "$d/sound"
 *	for h in bits kernel math math64 spinlock unaligned usb; do
 *		: > "$d/linux/$h.h"; done
 *	: > "$d/sound/control.h"; : > "$d/sound/core.h"; : > "$d/babyfacepro.h"
 *	cp babyfacepro-meter.c meter_selftest.c "$d"
 *	gcc -O2 -Wall -I "$d" -o "$d/meter_selftest" "$d/meter_selftest.c" -lm
 *	"$d/meter_selftest"
 *
 * Checks: peak and RMS of sines at 0, -6 and -20 dBFS, the capture
 * word map (marker words 4/5 never show), short frames at 96/192 kHz,
 * read-and-clear, over runs within and across URBs, and no overflow
 * over a long unread interval.
 */
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Kernel stubs: just enough for babyfacepro-meter.c. */
typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef int32_t s32;
typedef uint64_t u64;
typedef int spinlock_t;

#define BIT(n)			(1UL << (n))
#define ARRAY_SIZE(a)		(sizeof(a) / sizeof((a)[0]))
#define min_t(t, a, b)		((t)(a) < (t)(b) ? (t)(a) : (t)(b))
#define spin_lock_irqsave(l, f)		((void)(f))
#define spin_unlock_irqrestore(l, f)	((void)(f))

static inline u32 get_unaligned_le32(const u8 *p)
{
	return p[0] | p[1] << 8 | p[2] << 16 | (u32)p[3] << 24;
}

static inline u64 div_u64(u64 a, u32 b)
{
	return a / b;
}

static inline u32 int_sqrt64(u64 x)
{
	u64 r = (u64)sqrtl((long double)x);

	while (r * r > x)
		r--;
	while ((r + 1) * (r + 1) <= x)
		r++;
	return (u32)r;
}

#define SNDRV_PCM_STREAM_PLAYBACK	0
#define SNDRV_PCM_STREAM_CAPTURE	1
#define SNDRV_CTL_ELEM_TYPE_INTEGER	2
#define SNDRV_CTL_ELEM_IFACE_PCM	2
#define SNDRV_CTL_ELEM_ACCESS_READ	1
#define SNDRV_CTL_ELEM_ACCESS_VOLATILE	4

struct snd_ctl_elem_info {
	int type;
	unsigned int count;
	struct {
		struct {
			long min, max, step;
		} integer;
	} value;
};

struct snd_ctl_elem_value {
	struct {
		struct {
			long value[128];
		} integer;
	} value;
};

struct snd_kcontrol {
	unsigned long private_value;
	void *private_data;
};

struct snd_kcontrol_new {
	int iface;
	const char *name;
	int access;
	void *info;
	void *get;
	unsigned long private_value;
};

#define snd_kcontrol_chip(k)	((k)->private_data)

struct snd_card;

static inline int snd_ctl_add(struct snd_card *card, struct snd_kcontrol *k)
{
	return 0;
}

static inline struct snd_kcontrol *snd_ctl_new1(struct snd_kcontrol_new *t,
						void *data)
{
	return NULL;
}

/* The parts of babyfacepro.h the meter code uses. */
#define BF_METER_CHANNELS	12

struct bf_meter {
	u32 peak[BF_METER_CHANNELS];
	u64 sum_sq[BF_METER_CHANNELS];
	u32 frames;
	u32 run[BF_METER_CHANNELS];
	u32 overs[BF_METER_CHANNELS];
};

struct snd_usb_babyface {
	struct snd_card *card;
	unsigned int frame_bytes;
	spinlock_t meter_lock;
	struct bf_meter meter[2];
};

#include "babyfacepro-meter.c"

#define FS		0x7fffff
#define URB_FRAMES	256

static struct snd_usb_babyface chip;
static u8 buf[URB_FRAMES * 56];

static void put(u8 *p, s32 v)
{
	u32 w = (u32)v << 8;

	p[0] = w;
	p[1] = w >> 8;
	p[2] = w >> 16;
	p[3] = w >> 24;
}

/* One control read: all 12 channels, and the interval restarts. */
static void rd(int dir, int kind, long *out)
{
	struct snd_kcontrol k = {
		.private_value = (dir << 8) | kind,
		.private_data = &chip,
	};
	static struct snd_ctl_elem_value v;
	int i;

	memset(&v, 0, sizeof(v));
	bf_meter_get(&k, &v);
	for (i = 0; i < BF_METER_CHANNELS; i++)
		out[i] = v.value.integer.value[i];
}

static double db(long x)
{
	return x ? 20 * log10((double)x / FS) : -999;
}

static s32 sine(unsigned long n, double gain)
{
	return (s32)lround(sin(2 * M_PI * 1000 * n / 48000.0) * FS * gain);
}

static void check_rate(unsigned int fb)
{
	unsigned int words = fb / 4;
	long cp[12], cr[12], pp[12], pr[12], ov[12];
	unsigned long n = 0;
	int urb, f, ch;

	memset(&chip, 0, sizeof(chip));
	chip.frame_bytes = fb;

	/* Word 0 (capture ch0): full-scale sine.  Word 6 (capture ch4):
	 * -20 dB.  Words 4/5: the loud marker, which must not show.
	 * Word 11 (playback ch11): -6 dB, absent at 96/192 kHz.
	 */
	for (urb = 0; urb < 400; urb++) {
		memset(buf, 0, sizeof(buf));
		for (f = 0; f < URB_FRAMES; f++, n++) {
			u8 *fr = buf + f * fb;

			put(fr, sine(n, 1.0));
			put(fr + 4 * 4, FS);
			put(fr + 5 * 4, -0x800000);
			if (words > 6)
				put(fr + 6 * 4, sine(n, 0.1));
			if (words > 11)
				put(fr + 11 * 4, sine(n, 0.5));
		}
		bf_meter_capture(&chip, buf, URB_FRAMES);
		bf_meter_playback(&chip, buf, URB_FRAMES);
	}

	rd(SNDRV_PCM_STREAM_CAPTURE, BF_METER_PEAK, cp);
	rd(SNDRV_PCM_STREAM_CAPTURE, BF_METER_RMS, cr);
	rd(SNDRV_PCM_STREAM_PLAYBACK, BF_METER_PEAK, pp);
	rd(SNDRV_PCM_STREAM_PLAYBACK, BF_METER_RMS, pr);
	printf("frame %2u B: cap0 %.2f/%.2f  cap4 %.2f/%.2f  pb11 %.2f/%.2f dB\n",
	       fb, db(cp[0]), db(cr[0]), db(cp[4]), db(cr[4]),
	       db(pp[11]), db(pr[11]));

	assert(fabs(db(cp[0])) < 0.01 && fabs(db(cr[0]) + 3.01) < 0.02);
	assert(fabs(db(cp[4]) + 20) < 0.01 && fabs(db(cr[4]) + 23.01) < 0.02);
	assert(cp[2] == 0 && cp[3] == 0);	/* marker never leaks in */
	if (words > 11)
		assert(fabs(db(pp[11]) + 6.02) < 0.01 &&
		       fabs(db(pr[11]) + 9.03) < 0.02);
	else
		assert(pp[11] == 0 && pr[11] == 0);
	for (ch = 0; ch < BF_METER_CHANNELS; ch++)
		if (bf_capture_word_map[ch] >= words)
			assert(cp[ch] == 0);

	/* Reading cleared the interval. */
	rd(SNDRV_PCM_STREAM_CAPTURE, BF_METER_PEAK, cp);
	rd(SNDRV_PCM_STREAM_CAPTURE, BF_METER_RMS, cr);
	assert(cp[0] == 0 && cr[0] == 0);

	/* Overs: runs of 5 then 3 full-scale samples report 5. */
	memset(buf, 0, sizeof(buf));
	for (f = 0; f < 5; f++)
		put(buf + f * fb, -0x800000);
	for (f = 6; f < 9; f++)
		put(buf + f * fb, FS);
	bf_meter_capture(&chip, buf, 9);
	rd(SNDRV_PCM_STREAM_CAPTURE, BF_METER_OVERS, ov);
	assert(ov[0] == 5);
	rd(SNDRV_PCM_STREAM_CAPTURE, BF_METER_OVERS, ov);
	assert(ov[0] == 0);

	/* A run continues across URBs: 3 left over + 256 + 4. */
	memset(buf, 0, sizeof(buf));
	for (f = 0; f < URB_FRAMES; f++)
		put(buf + f * fb, FS);
	bf_meter_capture(&chip, buf, URB_FRAMES);
	bf_meter_capture(&chip, buf, 4);
	rd(SNDRV_PCM_STREAM_CAPTURE, BF_METER_OVERS, ov);
	assert(ov[0] == 263);
}

int main(void)
{
	long r[12];
	long i;
	int f;

	check_rate(56);		/* x1: 32-48 kHz */
	check_rate(40);		/* x2: 64-96 kHz */
	check_rate(32);		/* x4: 128-192 kHz */

	/* 76.8M frames unread: no u64 overflow, and the mean survives. */
	memset(&chip, 0, sizeof(chip));
	chip.frame_bytes = 56;
	memset(buf, 0, sizeof(buf));
	for (f = 0; f < URB_FRAMES; f++)
		put(buf + f * 56, FS);
	for (i = 0; i < 300000; i++)
		bf_meter_capture(&chip, buf, URB_FRAMES);
	rd(SNDRV_PCM_STREAM_CAPTURE, BF_METER_RMS, r);
	assert(db(r[0]) > -0.01);

	printf("ok meter_selftest\n");
	return 0;
}
