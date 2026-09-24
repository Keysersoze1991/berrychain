#!/usr/bin/env bash
# Enter the standing agent's two secrets on the server, without them ever
# passing through anyone else. Run as root on the seed:
#   bash /opt/berrychain/deploy/agent-secrets.sh
# Prompts are hidden. Writes /etc/berrychain/agent.env (root:berry, 640),
# then enables and starts the agent and shows its first log lines.
set -euo pipefail
ETC=/etc/berrychain
[ "$(id -u)" -eq 0 ] || { echo "run as root"; exit 1; }
[ -f "$ETC/agent.json" ] || { echo "missing $ETC/agent.json (run the setup first)"; exit 1; }
read -r -s -p "Anthropic API key (starts with sk-ant-, hidden): " KEY; echo
KEY=${KEY//$''/}; KEY=${KEY//[[:space:]]/}     # pasted text can carry a stray return or spaces
case "$KEY" in sk-ant-*) ;; *) echo "that does not look like an Anthropic API key (should start with sk-ant-)"; exit 1;; esac
read -r -s -p "Passphrase of the agent wallet (hidden): " PASS; echo
PASS=${PASS//$''/}
[ -n "$PASS" ] || { echo "empty passphrase"; exit 1; }
umask 077
printf 'ANTHROPIC_API_KEY=%s\nBERRY_WALLET_PASSPHRASE=%s\n' "$KEY" "$PASS" > "$ETC/agent.env"
chown root:berry "$ETC/agent.env"; chmod 640 "$ETC/agent.env"
unset KEY PASS
echo "== checking the passphrase opens the wallet"
WALLET=$(python3 -c "import json;print(json.load(open('$ETC/agent.json'))['wallet'])")
set +e
( set -a; . "$ETC/agent.env"; set +a; cd /opt/berrychain && sudo -u berry -E .venv/bin/python -m berrychain.cli wallet check "$WALLET" ) || { echo "!! wrong passphrase; run this script again"; exit 1; }
set -e
systemctl enable -q berrychain-agent
systemctl restart berrychain-agent
sleep 8
systemctl --no-pager --lines=0 status berrychain-agent | head -3
echo "== first log lines (the first tick takes a minute or two):"
journalctl -u berrychain-agent --no-pager -n 15 -o cat
echo
echo "follow it any time with:  journalctl -u berrychain-agent -f"
