#!/usr/bin/env bash
# Switch on the nightly copy of the seed's service state (see deploy/backup.sh for what is and is not in it).
# Idempotent; run as root on seed1:
#   bash /opt/berrychain/deploy/backup-setup.sh
# Then, from the PC, fetch the newest copy whenever you like:  scripts\pull-backup.ps1
set -euo pipefail
APP=/opt/berrychain

if [ "$(id -u)" -ne 0 ]; then echo "run as root"; exit 1; fi

# Pull first, then re-run this script from the fresh file, so a run always uses the version it pulled.
if [ "${BACKUP_SETUP_STAGE:-}" != "2" ]; then
  git config --global --add safe.directory "$APP" >/dev/null 2>&1 || true
  git -C "$APP" pull -q --ff-only origin main
  BACKUP_SETUP_STAGE=2 exec bash "$0" "$@"
fi

echo "== code"
git -C "$APP" log --oneline -1

echo "== timer"
install -m 644 "$APP/deploy/berrychain-backup.service" /etc/systemd/system/berrychain-backup.service
install -m 644 "$APP/deploy/berrychain-backup.timer" /etc/systemd/system/berrychain-backup.timer
systemctl daemon-reload
systemctl enable -q --now berrychain-backup.timer

echo "== first copy"
bash "$APP/deploy/backup.sh"
ls -l /var/backups/berrychain/
systemctl list-timers --all 'berrychain-backup*' --no-pager | head -3
echo "== done: a copy every night at 13:10 UTC, seven kept, in /var/backups/berrychain (root only)"
