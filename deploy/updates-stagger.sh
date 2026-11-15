#!/usr/bin/env bash
# Give this seed its own quiet hour for automatic system updates, so the two seeds never update (and have
# their services restarted) at the same moment. Stock Ubuntu runs both at 06:00 UTC plus up to an hour, which
# is early evening in eastern Australia and puts the two seeds minutes apart. After this:
#   seed1  package lists 15:45 UTC, upgrades 16:30 UTC
#   seed2  package lists 17:45 UTC, upgrades 18:30 UTC
# Idempotent; run as root on each seed:
#   bash /opt/berrychain/deploy/updates-stagger.sh          # works out which seed this is
#   bash /opt/berrychain/deploy/updates-stagger.sh seed2    # or say so
# To undo: rm -r /etc/systemd/system/apt-daily.timer.d /etc/systemd/system/apt-daily-upgrade.timer.d
#          systemctl daemon-reload; systemctl restart apt-daily.timer apt-daily-upgrade.timer
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then echo "run as root"; exit 1; fi

which="${1:-}"
if [ -z "$which" ]; then
  mine=" $(hostname -I 2>/dev/null) "
  for n in seed1 seed2; do
    ip=$(getent ahostsv4 "$n.berrychain.link" 2>/dev/null | awk '{print $1; exit}')
    if [ -n "$ip" ] && [ "${mine#* $ip }" != "$mine" ]; then which=$n; fi
  done
fi
case "$which" in
  seed1) lists="15:45"; upgrades="16:30" ;;
  seed2) lists="17:45"; upgrades="18:30" ;;
  *) echo "cannot tell which seed this is; run again with seed1 or seed2 as the argument"; exit 1 ;;
esac
echo "== $which: package lists at $lists UTC, upgrades at $upgrades UTC"

override() {   # timer name, time of day
  mkdir -p "/etc/systemd/system/$1.d"
  cat > "/etc/systemd/system/$1.d/berrychain.conf" <<EOF
# written by /opt/berrychain/deploy/updates-stagger.sh ($which)
[Timer]
OnCalendar=
OnCalendar=*-*-* $2 UTC
RandomizedDelaySec=5m
EOF
}
override apt-daily.timer "$lists"
override apt-daily-upgrade.timer "$upgrades"
systemctl daemon-reload
systemctl restart apt-daily.timer apt-daily-upgrade.timer

echo "== timers now"
systemctl list-timers --all 'apt*' --no-pager | head -4
echo "== done (a missed run may fire once straight away; that is the old schedule catching up)"
