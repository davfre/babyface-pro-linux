#!/bin/sh
# Superseded. The driver does this itself now, on the 'local: make the DIM
# button work' commit: it acts on the button press and attenuates AN1/2 and
# PH3/4 by 20 dB. Kept only for running against an unpatched driver.
#
# Make the front-panel DIM button act.
#
# The driver leaves acting on the front panel to TuxMix, so with the
# kernel driver alone the DIM button does nothing. This does it.
#
# Two things it deliberately does not use:
#
#   "Front Panel Dim", the driver's sticky DIM state, reads st[1] & 0x20.
#   On an original Babyface Pro that bit is set constantly, so the
#   control is stuck on and never moves. DIM there is momentary only:
#   st[3] flashes 0x60 per press. So this counts presses instead and
#   keeps the state itself.
#
#   "Dim Switch", the driver's own DIM, writes an absolute 0x0333 (819)
#   to the Phones master rather than attenuating what is there, and only
#   touches output 1. Below -20 dB it raises the level instead of
#   lowering it. So both outputs are handled here, relative to their
#   current level: save, divide by 10 (exactly -20 dB on the linear
#   0x2000 = 0 dB scale), restore on release.
#
#     AN1/2  main out, control index 0
#     PH3/4  phones, control index 1
#
# Needs the local "notify on front-panel button presses" driver commit,
# without which Front Panel Button updates silently and nothing here
# ever wakes up.
#
# Usage: bbf-dim-watch.sh [card] [--phones-only|--main-only]
set -eu

CARD="${1:-BabyfacePro}"
MODE="${2:-both}"

BTN_DIM=6			# BF_PANEL_BTN_DIM
CTL_BTN="name=Front Panel Button"
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
need "$CTL_BTN"
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

dim_one() {
	_cur=$(read_ctl "$1")
	_l=${_cur%%,*}
	_r=${_cur##*,}
	amixer -c "$CARD" -q cset "$1" "$((_l / 10)),$((_r / 10))"
	printf '%s\n' "$_cur"
}

engage() {
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

# The loop runs in the pipeline's subshell, so the state and the trap
# both have to live in here with it.
alsactl monitor "$CTL" | {
	saved_main=''
	saved_phones=''
	dimmed=0

	# Without this, stopping the service while dimmed would leave the
	# outputs 20 dB down with nothing left running to put them back.
	trap 'release; exit 0' INT TERM

	while read -r line; do
		if [ -n "${BBF_DEBUG:-}" ]; then
			echo "event: $line" >&2
		fi
		case "$line" in
		*"Front Panel Button"*)	;;
		*)			continue ;;
		esac
		_btn=$(read_ctl "$CTL_BTN")
		if [ -n "${BBF_DEBUG:-}" ]; then
			echo "  button=$_btn dimmed=$dimmed" >&2
		fi
		[ "$_btn" = "$BTN_DIM" ] || continue
		if [ "$dimmed" = 0 ]; then
			engage
			dimmed=1
			echo "dim on" >&2
		else
			release
			dimmed=0
			echo "dim off" >&2
		fi
	done

	# Falling out means alsactl stopped. The loop's own status is 0, so
	# without this the watcher would exit cleanly and Restart=on-failure
	# would not bring it back.
	release
	die "alsactl monitor exited, no longer watching"
}
