#!/bin/sh
# Make the front-panel DIM button act.
#
# The driver decodes the button into the read-only "Front Panel Dim"
# control but never acts on it: that is left to TuxMix. This mirrors it
# onto "Dim Switch", which applies the hardware's own -20 dB to the
# Phones master and restores the previous level on release.
#
# Usage: bbf-dim-watch.sh [card]     (card name or index, default BabyfacePro)
set -eu

CARD="${1:-BabyfacePro}"

for c in 'Front Panel Dim' 'Dim Switch'; do
	amixer -c "$CARD" cget name="$c" >/dev/null 2>&1 || {
		echo "no '$c' control on card $CARD" >&2
		exit 1
	}
done

read_ctl() {
	amixer -c "$CARD" cget name="$1" | sed -n 's/^  : values=//p' | head -1
}

last=''
sync_dim() {
	want=$(read_ctl 'Front Panel Dim')
	[ "$want" = "$last" ] && return 0
	amixer -c "$CARD" -q cset name='Dim Switch' "$want"
	last="$want"
}

sync_dim
alsactl monitor "$CARD" | while read -r _; do sync_dim; done
