/* disp_selftest.c - check of bf_mix_display (the MIX-mode VU display
 * law) against the captured anchors.
 *
 * The helper is the driver's own, pulled out of babyfacepro-ctl.c by
 * extract_laws.py - run through selftests.sh.
 *
 * laws: bf_mix_display
 */
#include <stdio.h>

int fails;

static void chk(int db, int want)
{
	int got = bf_mix_display(db * 2);
	if (got != want) {
		printf("FAIL db=%3d dB -> disp %d want %d\n", db, got, want);
		fails++;
	} else {
		printf("ok   %3d dB -> disp %d\n", db, got);
	}
}

int main(void)
{
	/* captured anchors (cap_mix + cap_panel) — db2 exact */
	chk(-62, 0); chk(-54, 1); chk(-48, 2); chk(-42, 3); chk(-35, 4);
	chk(-28, 5); chk(-6, 11); chk(-4, 12);
	/* the cap_panel fader db2 values hit the anchors exactly */
	if (bf_mix_display(-15) != 10 || bf_mix_display(-13) != 11 ||
	    bf_mix_display(-9) != 12) {
		printf("FAIL db2 anchors: %d %d %d\n", bf_mix_display(-15),
		       bf_mix_display(-13), bf_mix_display(-9));
		fails++;
	}
	/* monotonic up */
	int prev = -1;
	for (int db = -70; db <= 6; db++) {
		int d = bf_mix_display(db * 2);
		if (d < prev) { printf("FAIL non-monotonic at %d\n", db); fails++; }
		prev = d;
	}
	/* floor / ceiling */
	chk(-70, 0);
	printf(fails ? "== %d FAILURES ==\n" : "== ALL OK ==\n", fails);
	return fails != 0;
}
