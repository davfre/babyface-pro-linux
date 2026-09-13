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

die() {
	echo "bbf-dim-watch: $*" >&2
	exit 1
}

need() {
	amixer -c "$CARD" cget name="$1" >/dev/null 2>&1 ||
		die "no '$1' control on card $CARD"
}

amixer -c "$CARD" controls >/dev/null 2>&1 || die "no such card: $CARD"

# amixer takes a bare card id or index; alsactl wants a full CTL name.
case "$CARD" in
*:*)	CTL="$CARD" ;;
*)	CTL="hw:$CARD" ;;
esac
need 'Front Panel Dim'
if [ "$MODE" != "--main-only" ]; then need 'Dim Switch'; fi
if [ "$MODE" != "--phones-only" ]; then need 'AN1/2 Playback Volume'; fi

# A pipeline's status is the last command's, so a failed amixer here
# would otherwise surface as an empty string rather than an error, and
# the caller would go on to do arithmetic on it.
read_ctl() {
	_v=$(amixer -c "$CARD" cget name="$1" 2>/dev/null |
		sed -n 's/^  : values=//p' | head -1)
	[ -n "$_v" ] || die "could not read '$1' on card $CARD"
	printf '%s\n' "$_v"
}

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

last=$(read_ctl 'Front Panel Dim')

# The loop runs in the pipeline's subshell, so 'saved' and the trap both
# have to live in here with it.
alsactl monitor "$CTL" | {
	saved=''
	# Without this, stopping the service while dimmed would leave the
	# monitors 20 dB down with nothing left running to put them back.
	trap 'release; exit 0' INT TERM

	# Apply the button's current state rather than waiting for the next
	# press, or starting up with DIM already engaged would look dead
	# until it had been pressed twice.
	#
	# The exception is Dim Switch already being on: that means an
	# earlier run engaged and did not get to release, so the pre-dim
	# AN1/2 level is gone and re-saving would latch the dimmed one.
	if [ "$last" = "on" ]; then
		if [ "$MODE" != "--main-only" ] &&
		   [ "$(read_ctl 'Dim Switch')" = "on" ]; then
			echo "bbf-dim-watch: already dimmed by an earlier run," \
				"leaving AN1/2 alone until the next release" >&2
		else
			engage
		fi
	fi

	while read -r _; do
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

	# Falling out means alsactl stopped. The loop's own status is 0, so
	# without this the watcher would exit cleanly and Restart=on-failure
	# would not bring it back.
	die "alsactl monitor exited, no longer watching"
}
