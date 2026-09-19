#!/bin/sh
# selftests.sh — automated checks for snd-usb-babyface-pro WITHOUT the
# card: the law selftests (fader/master/display), the module build, and
# checkpatch.  The hardware regress (regress.sh) is separate — it needs
# the card + a free device.
#
# Usage: sh selftests.sh          (from tools/kernel or the repo root)
set -u
cd "$(dirname "$0")"
FAIL=0

echo "== law selftests =="
for t in fader_selftest master_selftest disp_selftest eq_selftest; do
	LM=""
	[ "$t" = eq_selftest ] && LM="-lm"
	if gcc -O2 -Wall -o "/tmp/$t" "$t.c" $LM && "/tmp/$t" > /tmp/$t.out 2>&1; then
		echo "  PASS  $t"
		grep -E '^ok' /tmp/$t.out | tail -1 > /dev/null
	else
		echo "  FAIL  $t"
		tail -5 /tmp/$t.out
		FAIL=1
	fi
done

echo "== meter selftest =="
# Builds babyfacepro-meter.c itself against stubs; see meter_selftest.c.
d=$(mktemp -d)
mkdir "$d/linux" "$d/sound"
for h in bits kernel math math64 spinlock unaligned usb; do : > "$d/linux/$h.h"; done
: > "$d/sound/control.h"; : > "$d/sound/core.h"; : > "$d/babyfacepro.h"
cp babyfacepro-meter.c meter_selftest.c "$d"
if gcc -O2 -Wall -I "$d" -o "$d/meter_selftest" "$d/meter_selftest.c" -lm &&
   "$d/meter_selftest" > /tmp/meter_selftest.out 2>&1; then
	echo "  PASS  meter_selftest"
else
	echo "  FAIL  meter_selftest"
	tail -5 /tmp/meter_selftest.out
	FAIL=1
fi
rm -rf "$d"

echo "== module build =="
KSRC=/lib/modules/$(uname -r)/build
if make LLVM=1 -C "$KSRC" M="$PWD" modules > /tmp/kbuild.out 2>&1; then
	echo "  PASS  make modules"
else
	echo "  FAIL  make modules"
	tail -10 /tmp/kbuild.out
	FAIL=1
fi

echo "== checkpatch =="
KP="$KSRC/scripts/checkpatch.pl"
if [ -x "$KP" ]; then
	for f in babyfacepro.c babyfacepro-ctl.c babyfacepro-meter.c babyfacepro.h; do
		if $KP --no-tree --strict -f "$f" 2>&1 | grep -qE 'ERROR|WARNING'; then
			echo "  WARN  $f (see checkpatch below)"
			$KP --no-tree --strict -f "$f" 2>&1 | grep -E 'ERROR|WARNING'
			FAIL=1
		else
			echo "  PASS  $f"
		fi
	done
else
	echo "  SKIP  checkpatch (no $KP)"
fi

echo "== RESULT: $([ $FAIL -eq 0 ] && echo ALL OK || echo FAILURES) =="
exit $FAIL
