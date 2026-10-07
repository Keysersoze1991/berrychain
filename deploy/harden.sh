#!/usr/bin/env bash
# Applies the fixes that deploy/hardening-check.sh reports on a seed. Idempotent;
# safe to run twice. Run it as root on the seed, from the repo checkout:
#
#   ssh -i ~/.ssh/berrychain_seed root@seed1.berrychain.link 'cd /opt/berrychain && git pull -q && bash deploy/harden.sh'
#
# What it does, and why:
#   fail2ban            bans addresses that hammer SSH
#   sshd drop-in        no password logins, root only with a key, no keyboard-interactive
#                       (refused unless root already has an authorized key, so you cannot lock yourself out)
#   file modes          env files, the APNs key and the agent's wallet/state readable by root only
#   xrdp / remote desktop  disabled and masked if present: a seed has no desktop and must not
#                       expose 3389/3350 to the internet
#   unattended-upgrades installed and enabled if missing
# It does NOT reboot. If the check says a reboot is pending, do it when convenient:
#   systemctl reboot   (the node catches up from the other seed; the agent and relay restart on their own)
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }
export DEBIAN_FRONTEND=noninteractive

echo "== fail2ban"
if ! systemctl is-active --quiet fail2ban 2>/dev/null; then
  apt-get install -y -q fail2ban >/dev/null
  cat > /etc/fail2ban/jail.d/berrychain.conf <<'EOF'
[sshd]
enabled = true
maxretry = 5
findtime = 10m
bantime = 1h
EOF
  systemctl enable --now fail2ban
fi
systemctl is-active fail2ban

echo "== sshd"
if [ -s /root/.ssh/authorized_keys ]; then
  cat > /etc/ssh/sshd_config.d/90-berrychain.conf <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
PubkeyAuthentication yes
EOF
  sshd -t && systemctl reload ssh
  sshd -T | grep -E '^(passwordauthentication|permitrootlogin|kbdinteractiveauthentication) '
else
  echo "root has no authorized key; leaving password login ON so you are not locked out"
fi

echo "== file modes"
for f in /etc/berrychain/*.env /etc/berrychain/apns.p8 /var/lib/berrychain/agent/*.json /var/lib/berrychain/push/*.json; do
  [ -e "$f" ] && chmod 600 "$f" && echo "600 $f"
done

echo "== remote desktop"
for u in xrdp xrdp-sesman; do
  if systemctl list-unit-files 2>/dev/null | grep -q "^$u.service"; then
    systemctl disable --now "$u" 2>/dev/null || true
    systemctl mask "$u" 2>/dev/null || true
    echo "$u disabled and masked"
  fi
done
if ss -ltnH | awk '{print $4}' | grep -qE ':(3389|3350)$'; then
  echo "WARNING: something still listens on 3389/3350:"; ss -ltnp | grep -E ':(3389|3350)\b' || true
fi

echo "== unattended-upgrades"
dpkg -s unattended-upgrades >/dev/null 2>&1 || apt-get install -y -q unattended-upgrades >/dev/null
grep -qs 'Unattended-Upgrade "1"' /etc/apt/apt.conf.d/20auto-upgrades || cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF
echo "ok"

echo "== done; re-check with: bash deploy/hardening-check.sh"
