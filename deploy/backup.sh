#!/usr/bin/env bash
# The nightly copy of what the seed's services have learned and paid: the Harbourmaster's memory, journal and
# threads, the plank boards and purse records, the ride records. Run by berrychain-backup.timer; by hand:
#   bash /opt/berrychain/deploy/backup.sh
#
# Deliberately NOT in the copy:
#   - wallets, passphrases, API keys, the push key (/etc/berrychain, and any wallet file kept beside the state):
#     those live on the offline sticks and are never gathered into one archive
#   - push pairings and parcels: the privacy page promises both are forgotten on request and after 30 days,
#     and a copy kept elsewhere would break that promise
#   - the chain: every node has it
# The archive is readable by root only. Fetch it to another machine with scripts/pull-backup.ps1.
set -euo pipefail
DATA=/var/lib/berrychain
OUT=/var/backups/berrychain
KEEP=${BACKUP_KEEP:-7}

if [ "$(id -u)" -ne 0 ]; then echo "run as root"; exit 1; fi
umask 077
mkdir -p "$OUT"
chmod 700 "$OUT"

dirs=()
for d in agent plank ride; do
  [ -d "$DATA/$d" ] && dirs+=("$d")
done
if [ "${#dirs[@]}" -eq 0 ]; then echo "nothing to back up on this machine"; exit 0; fi

name="services-$(date -u +%Y%m%d-%H%M%S).tar.gz"
# A file may change while it is read (the services keep running); tar reports that with status 1, which is
# fine here because every state file is written whole and renamed into place.
set +e
tar -C "$DATA" -czf "$OUT/$name.part" \
  --exclude='builder-agent.json' --exclude='*wallet*.json' --exclude='*.env' --exclude='*.p8' --exclude='*.key' --exclude='*.tmp' \
  "${dirs[@]}"
status=$?
set -e
if [ "$status" -gt 1 ]; then rm -f "$OUT/$name.part"; echo "tar failed ($status)"; exit "$status"; fi
gzip -t "$OUT/$name.part"
mv "$OUT/$name.part" "$OUT/$name"
ln -sfn "$name" "$OUT/latest.tar.gz"

# keep the newest few
ls -1t "$OUT"/services-*.tar.gz | tail -n +"$((KEEP + 1))" | while read -r old; do rm -f "$old"; done

echo "backup: $OUT/$name ($(du -h "$OUT/$name" | cut -f1), ${dirs[*]}); $(ls -1 "$OUT"/services-*.tar.gz | wc -l) kept"
