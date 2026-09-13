#!/usr/bin/env bash
# Probe an RME Babyface Pro (non-FS) so we can compare it with the
# Babyface Pro FS the snd-usb-babyface-pro driver was written for.
# Run once in CLASS-COMPLIANT mode, then again in PROPRIETARY mode
# (toggle: hold SELECT + DIM while plugging the power/USB in).
#   ./bbf-probe.sh cc      -> writes probe-cc.txt
#   ./bbf-probe.sh pc      -> writes probe-pc.txt
set -u
tag="${1:-unknown}"
out="$(dirname "$0")/probe-$tag.txt"
exec > >(tee "$out") 2>&1

echo "=== date / kernel ==="
date -Is; uname -a
echo; echo "=== distro ==="
cat /etc/os-release 2>/dev/null | head -4
echo; echo "=== kernel build tree present? (needed to build the module) ==="
ls -d /lib/modules/$(uname -r)/build 2>&1
echo; echo "=== RME devices (2a39) ==="
lsusb -d 2a39: || echo "no 2a39 device found"
echo; echo "=== full descriptors ==="
sudo lsusb -v -d 2a39: 2>/dev/null || lsusb -v -d 2a39: 2>/dev/null
echo; echo "=== sysfs summary ==="
for d in /sys/bus/usb/devices/*/; do
  v=$(cat "$d/idVendor" 2>/dev/null) || continue
  [ "$v" = "2a39" ] || continue
  echo "--- $d"
  for f in idVendor idProduct bcdDevice manufacturer product serial version speed bNumInterfaces; do
    printf '%-16s %s\n' "$f" "$(cat "$d/$f" 2>/dev/null)"
  done
  echo "drivers bound:"; ls -l "$d"/*/driver 2>/dev/null | sed 's/.*-> //'
done
echo; echo "=== ALSA cards ==="
cat /proc/asound/cards 2>/dev/null
for s in /proc/asound/card*/stream0; do [ -e "$s" ] && { echo "--- $s"; cat "$s"; }; done
echo; echo "=== modules loaded ==="
lsmod | grep -iE 'snd_usb|snd-usb' 
echo; echo "=== recent kernel messages ==="
sudo dmesg 2>/dev/null | grep -iE 'usb|snd|rme|babyface' | tail -40 || \
  journalctl -k -n 200 --no-pager 2>/dev/null | grep -iE 'usb|snd|rme|babyface' | tail -40
echo; echo "=== done -> $out ==="
