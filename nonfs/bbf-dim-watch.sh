#!/bin/sh
# Make the front-panel DIM button act.
#
# The driver decodes the button into the read-only "Front Panel Dim"
# control but never acts on it: that is left to TuxMix. With the kernel
# driver alone the button does nothing.
#
# It does have a "Dim Switch" control, but this does not use it. That
# one writes an absolute 0x0333 (819) to the Phones master, taken from
# a capture made with the master near unity, rather than attenuating
# whatever is there. Below -20 dB it therefore raises the level instead
# of lowering it, and at the driver's own -30 dB default it is a boost
# of about 6 dB. Measured on an original Babyface Pro.
#
# So both outputs are handled here, relative to their current level:
# save, divide by 10 (exactly -20 dB on the linear 0x2000 = 0 dB
# scale), restore on release.
#
#   AN1/2  main out, control index 0
#   PH3/4  phones, control index 1
#
# Usage: bbf-dim-watch.sh [card] [--phones-only|--main-only]
set -eu

CARD="${1:-BabyfacePro}"
MODE="${2:-both}"

CTL_MAIN="name=AN1/2 Playback Volume"
CTL_PHONES="name=PH3/4 Playback Volume,index=1"

die() {
	echo "bbf-dim-watch: $*" >&2
	exit 1
}

amixer -c "$CARD" controls >/dev/null 2>&1 || die "no such card: $CARD"

need() {
	amixer -c "$CARD" cget "$1" >/dev/null 2>&1 || die "no control '$1' on $CARD"
}
need "name=Front Panel Dim"
if [ "$MODE" != "--phones-only" ]; then need "$CTL_MAIN"; fi
if [ "$MODE" != "--main-only" ]; then need "$CTL_PHONES"; fi

# A pipeline's status is the last command's, so a failed amixer here
# would otherwise surface as an empty string rather than an error, and
# the caller would go on to do arithmetic on it.
read_ctl() {
	_v=$(amixer -c "$CARD" cget "$1" 2>/dev/null |
		sed -n 's/^  : values=//p' | head -1)
	[ -n "$_v" ] || die "could not read '$1' on $CARD"
	printf '%s\n' "$_v"
}

# Save once per engage: a second engage without a release in between
# must not latch the dimmed level as the thing to restore.
dim_one() {
	_cur=$(read_ctl "$1")
	_l=${_cur%%,*}
	_r=${_cur##*,}
	amixer -c "$CARD" -q cset "$1" "$((_l / 10)),$((_r / 10))"
	printf '%s\n' "$_cur"
}

engage() {
	if [ -n "$saved_main$saved_phones" ]; then
		return 0
	fi
	if [ "$MODE" != "--phones-only" ]; then
		saved_main=$(dim_one "$CTL_MAIN")
	fi
	if [ "$MODE" != "--main-only" ]; then
		saved_phones=$(dim_one "$CTL_PHONES")
	fi
}

release() {
	if [ -n "$saved_main" ]; then
		amixer -c "$CARD" -q cset "$CTL_MAIN" "$saved_main"
		saved_main=''
	fi
	if [ -n "$saved_phones" ]; then
		amixer -c "$CARD" -q cset "$CTL_PHONES" "$saved_phones"
		saved_phones=''
	fi
}

# amixer takes a bare card id or index; alsactl wants a full CTL name.
case "$CARD" in
*:*)	CTL="$CARD" ;;
*)	CTL="hw:$CARD" ;;
esac

last=$(read_ctl "name=Front Panel Dim")

# The loop runs in the pipeline's subshell, so the saved levels and the
# trap both have to live in here with it.
alsactl monitor "$CTL" | {
	saved_main=''
	saved_phones=''

	# Without this, stopping the service while dimmed would leave the
	# outputs 20 dB down with nothing left running to put them back.
	trap 'release; exit 0' INT TERM

	# Apply the button's current state rather than waiting for the next
	# press, or starting up with DIM already engaged would look dead
	# until it had been pressed twice.
	if [ "$last" = "on" ]; then
		engage
	fi

	while read -r _; do
		now=$(read_ctl "name=Front Panel Dim")
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
	release
	die "alsactl monitor exited, no longer watching"
}
