#!/usr/bin/env bash
# Read-only hardening check for a BerryChain seed (Ubuntu). Prints one line per
# item, PASS or WARN, and a fix hint for every WARN. Changes nothing.
#
#   ssh -i ~/.ssh/berrychain_seed root@seed1.berrychain.link 'bash -s' < deploy/hardening-check.sh
#
# Covers: automatic security updates, fail2ban, SSH password/root login, the
# firewall, listening ports, the BerryChain services and their file modes.

pass() { printf 'PASS  %s\n' "$1"; }
warn() { printf 'WARN  %s\n      fix: %s\n' "$1" "$2"; }

echo "== $(hostname) $(date -u +%Y-%m-%dT%H:%MZ) $(. /etc/os-release && echo "$PRETTY_NAME")"

# 1. unattended security updates
if dpkg -s unattended-upgrades >/dev/null 2>&1; then
  if grep -qs 'Unattended-Upgrade "1"' /etc/apt/apt.conf.d/20auto-upgrades; then
    pass "unattended-upgrades installed and enabled"
  else
    warn "unattended-upgrades installed but not enabled" "dpkg-reconfigure -plow unattended-upgrades"
  fi
else
  warn "unattended-upgrades not installed" "apt-get install -y unattended-upgrades && dpkg-reconfigure -plow unattended-upgrades"
fi
if [ -f /var/run/reboot-required ]; then
  warn "a reboot is pending for an installed kernel/library update" "schedule a reboot (the node resyncs from its peer)"
else
  pass "no reboot pending"
fi

# 2. fail2ban
if systemctl is-active --quiet fail2ban 2>/dev/null; then
  pass "fail2ban active ($(fail2ban-client status sshd 2>/dev/null | awk '/Currently banned/{print $NF" banned now"}'))"
else
  warn "fail2ban not running" "apt-get install -y fail2ban && systemctl enable --now fail2ban"
fi

# 3. sshd: effective config, including drop-ins
eff=$(sshd -T 2>/dev/null)
v() { echo "$eff" | awk -v k="$1" '$1==k{print $2}'; }
[ "$(v passwordauthentication)" = "no" ] && pass "sshd PasswordAuthentication no" \
  || warn "sshd allows password logins" "echo 'PasswordAuthentication no' > /etc/ssh/sshd_config.d/00-berrychain.conf && systemctl reload ssh"
case "$(v permitrootlogin)" in
  prohibit-password|without-password|no) pass "sshd PermitRootLogin $(v permitrootlogin)";;
  *) warn "sshd PermitRootLogin $(v permitrootlogin)" "echo 'PermitRootLogin prohibit-password' >> /etc/ssh/sshd_config.d/00-berrychain.conf && systemctl reload ssh";;
esac
[ "$(v kbdinteractiveauthentication)" = "no" ] && pass "sshd KbdInteractiveAuthentication no" \
  || warn "sshd keyboard-interactive auth on" "echo 'KbdInteractiveAuthentication no' >> /etc/ssh/sshd_config.d/00-berrychain.conf && systemctl reload ssh"
[ "$(v pubkeyauthentication)" = "yes" ] && pass "sshd PubkeyAuthentication yes" || warn "sshd public-key auth off" "set PubkeyAuthentication yes"
n=$(wc -l < /root/.ssh/authorized_keys 2>/dev/null || echo 0)
[ "$n" -ge 1 ] && pass "root has $n authorized key(s)" || warn "no authorized keys for root" "add the deploy key before turning passwords off"

# 4. firewall: only 22, 80, 443 should face the world; node/relay/room ports stay on loopback
if command -v ufw >/dev/null && ufw status 2>/dev/null | grep -q 'Status: active'; then
  pass "ufw active: $(ufw status 2>/dev/null | awk 'NR>3 && $2=="ALLOW"{printf "%s ", $1}')"
else
  warn "ufw not active" "ufw allow OpenSSH && ufw allow 80,443/tcp && ufw --force enable"
fi
public=$(ss -ltnH 2>/dev/null | awk '{print $4}' | grep -vE '^(127\.|\[::1\]|localhost)' | sed 's/.*://' | sort -un | tr '\n' ' ')
case " $public " in
  *" 8801 "*|*" 8803 "*|*" 8804 "*) warn "a BerryChain service listens on a public interface ($public)" "bind the node, relay and parcel room to 127.0.0.1 and let nginx front them";;
  *) pass "public listeners: ${public:-none}";;
esac

# 5. services
for s in berrychain-node berrychain-agent berrychain-push berrychain-parcels nginx; do
  if systemctl list-unit-files 2>/dev/null | grep -q "^$s.service"; then
    st=$(systemctl is-active "$s" 2>/dev/null)
    if [ "$st" = active ] && [ "$(systemctl show -p NRestarts --value "$s" 2>/dev/null)" -lt 5 ]; then pass "$s active"
    else warn "$s is $st (restarts: $(systemctl show -p NRestarts --value "$s" 2>/dev/null))" "journalctl -u $s -n 30 --no-pager"; fi
  fi
done

# 6. secrets on disk: /etc/berrychain root:berry 640 (the services run as berry and read
#    the APNs key themselves); the agent's and relay's state files 600 and theirs
for f in /etc/berrychain/*; do
  [ -f "$f" ] || continue
  m=$(stat -c %a "$f"); g=$(stat -c %G "$f"); u=$(stat -c %U "$f")
  if [ "$u" = root ] && [ "$g" = berry ] && { [ "$m" = 640 ] || [ "$m" = 600 ]; }; then pass "$f $u:$g $m"
  else warn "$f is $u:$g $m" "chown root:berry $f && chmod 640 $f"; fi
done
for f in /var/lib/berrychain/agent/*.json /var/lib/berrychain/push/*.json; do
  [ -e "$f" ] || continue
  m=$(stat -c %a "$f"); u=$(stat -c %U "$f")
  if [ "$u" = berry ] && { [ "$m" = 600 ] || [ "$m" = 400 ]; }; then pass "$f $u $m"; else warn "$f is $u $m" "chown berry:berry $f && chmod 600 $f"; fi
done

# 7. clock (block timestamps depend on it)
if timedatectl show 2>/dev/null | grep -q 'NTPSynchronized=yes'; then pass "clock NTP-synchronised"; else warn "clock not NTP-synchronised" "timedatectl set-ntp true"; fi

# 8. node health
if h=$(curl -fsS -m 5 http://127.0.0.1:8801/status 2>/dev/null); then
  pass "node answers: height $(echo "$h" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d["height"],"version",d.get("version","<0.9.1"),"refused reorgs",d.get("refused_reorgs","?"))')"
else
  warn "local node does not answer on 8801" "systemctl status berrychain-node"
fi
echo "== done"
