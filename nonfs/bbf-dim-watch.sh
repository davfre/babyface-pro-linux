#!/bin/sh
# Make the front-panel DIM button act.
#
# The driver decodes the button into the read-only "Front Panel Dim"
# control but never acts on it: that is left to TuxMix. With the kernel
# driver alone the button does nothing.
#
# This mirrors it onto two things:
#
#   PH3/4  "Dim Switch", the driver's own DIM. It writes the hardware's
#          absolute -20 dB to the Phones master and restores the
#          previous level on release.
#
#   AN1/2  handled here. The driver's DIM is hardcoded to output 1
#          (Phones), because the capture it was derived from was taken
#          with Phones selected. The main out is left alone, so this
#          saves "AN1/2 Playback Volume", divides it by 10 (exactly
#          -20 dB on a linear 0x2000 = 0 dB scale) and puts it back on
#          release.
#
# Usage: bbf-dim-watch.sh [card] [--phones-only|--main-only]
set -eu

CARD="${1:-BabyfacePro}"
MODE="${2:-both}"

need() {
	amixer -c "$CARD" cget name="$1" >/dev/null 2>&1 || {
		echo "no '$1' control on card $CARD" >&2
		exit 1
	}
}
need 'Front Panel Dim'
if [ "$MODE" != "--main-only" ]; then need 'Dim Switch'; fi
if [ "$MODE" != "--phones-only" ]; then need 'AN1/2 Playback Volume'; fi

read_ctl() {
	amixer -c "$CARD" cget name="$1" | sed -n 's/^  : values=//p' | head -1
}

saved=''

engage() {
	if [ "$MODE" != "--main-only" ]; then
		amixer -c "$CARD" -q cset name='Dim Switch' on
	fi
	if [ "$MODE" = "--phones-only" ]; then
		return 0
	fi
	# Only save once: a restart while already dimmed must not capture
	# the dimmed level as the thing to restore.
	if [ -n "$saved" ]; then
		return 0
	fi
	saved=$(read_ctl 'AN1/2 Playback Volume')
	l=${saved%%,*}
	r=${saved##*,}
	amixer -c "$CARD" -q cset name='AN1/2 Playback Volume' \
		"$((l / 10)),$((r / 10))"
}

release() {
	if [ "$MODE" != "--main-only" ]; then
		amixer -c "$CARD" -q cset name='Dim Switch' off
	fi
	if [ "$MODE" = "--phones-only" ]; then
		return 0
	fi
	if [ -z "$saved" ]; then
		return 0
	fi
	amixer -c "$CARD" -q cset name='AN1/2 Playback Volume' "$saved"
	saved=''
}

last=$(read_ctl 'Front Panel Dim')	# adopt the current state, do not act

alsactl monitor "$CARD" | while read -r _; do
	now=$(read_ctl 'Front Panel Dim')
	if [ "$now" = "$last" ]; then
		continue
	fi
	last="$now"
	case "$now" in
	on)	engage ;;
	off)	release ;;
	esac
done
