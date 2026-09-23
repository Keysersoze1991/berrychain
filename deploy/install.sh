#!/usr/bin/env bash
# BerryChain seed node installer for Ubuntu 22.04 / 24.04. Idempotent.
#
#   SEED_HOST=seed1.berrychain.link PEERS="https://seed2.berrychain.link" \
#   MINER_ADDRESS=brry1... ADMIN_EMAIL=you@example.com bash install.sh
#
# Env:
#   SEED_HOST      public DNS name of this server (required)
#   PEERS          comma-separated https URLs of the other seeds (optional)
#   MINER_ADDRESS  address that receives this seed's block rewards (optional: no mining)
#   ADMIN_EMAIL    for Let's Encrypt registration (required the first time)
#   REPO           git URL (default: the public BerryChain repository)
#   BRANCH         git branch or tag (default: main)
set -euo pipefail

: "${SEED_HOST:?set SEED_HOST to the public DNS name of this server}"
REPO="${REPO:-https://github.com/Keysersoze1991/berrychain.git}"
BRANCH="${BRANCH:-main}"
PEERS="${PEERS:-}"
MINER_ADDRESS="${MINER_ADDRESS:-}"
APP=/opt/berrychain
ETC=/etc/berrychain
DATA=/var/lib/berrychain

if [ "$(id -u)" -ne 0 ]; then echo "run as root"; exit 1; fi

echo "== packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git python3 python3-venv python3-pip nginx certbot python3-certbot-nginx ufw >/dev/null

echo "== user and directories"
id berry >/dev/null 2>&1 || useradd --system --home "$DATA" --shell /usr/sbin/nologin berry
mkdir -p "$DATA" "$ETC"
chown berry:berry "$DATA"
chmod 750 "$DATA"

echo "== code (owned by root, read-only to the service)"
git config --global --add safe.directory "$APP" >/dev/null 2>&1 || true
if [ -d "$APP/.git" ]; then
  git -C "$APP" fetch -q origin && git -C "$APP" checkout -q "$BRANCH" && git -C "$APP" pull -q --ff-only origin "$BRANCH"
else
  git clone -q --branch "$BRANCH" "$REPO" "$APP"
fi
python3 -m venv "$APP/.venv"
"$APP/.venv/bin/pip" install -q --upgrade pip
"$APP/.venv/bin/pip" install -q -r "$APP/requirements.txt"
chmod 755 "$APP/deploy/run-node.sh"

echo "== environment"
if [ ! -f "$ETC/node.env" ]; then
  ADMIN_TOKEN="$(head -c 32 /dev/urandom | base64 | tr -d '/+=' | head -c 40)"
  sed -e "s#__SEED_HOST__#$SEED_HOST#" -e "s#__PEERS__#$PEERS#" -e "s#__MINER__#$MINER_ADDRESS#" \
      -e "s#__ADMIN_TOKEN__#$ADMIN_TOKEN#" "$APP/deploy/node.env.example" > "$ETC/node.env"
  chmod 640 "$ETC/node.env"; chown root:berry "$ETC/node.env"
  echo "   wrote $ETC/node.env (admin token generated; keep this file private)"
else
  echo "   keeping existing $ETC/node.env"
fi

echo "== systemd"
install -m 644 "$APP/deploy/berrychain-node.service" /etc/systemd/system/berrychain-node.service
systemctl daemon-reload
systemctl enable -q berrychain-node

echo "== nginx"
if [ ! -f /etc/nginx/sites-available/berrychain ]; then
  sed -e "s#__SEED_HOST__#$SEED_HOST#g" "$APP/deploy/nginx-seed.conf" > /etc/nginx/sites-available/berrychain
  echo "   wrote /etc/nginx/sites-available/berrychain"
else
  # certbot edits this file to add the TLS listener; never overwrite it on a re-run
  echo "   keeping existing /etc/nginx/sites-available/berrychain (delete it to regenerate, then re-run certbot)"
fi
ln -sf /etc/nginx/sites-available/berrychain /etc/nginx/sites-enabled/berrychain
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

echo "== firewall"
ufw allow OpenSSH >/dev/null
ufw allow 'Nginx Full' >/dev/null
ufw --force enable >/dev/null

if [ ! -d "/etc/letsencrypt/live/$SEED_HOST" ]; then
  : "${ADMIN_EMAIL:?set ADMIN_EMAIL for the Lets Encrypt account}"
  echo "== certificate"
  certbot --nginx -n --agree-tos -m "$ADMIN_EMAIL" -d "$SEED_HOST" --redirect
fi

if [ ! -f "$APP/genesis.json" ]; then
  echo
  echo "!! copy the launch genesis.json to $APP/genesis.json, then: systemctl start berrychain-node"
  exit 0
fi
chmod 644 "$APP/genesis.json"
systemctl restart berrychain-node
sleep 2
systemctl --no-pager --lines=5 status berrychain-node || true
echo "== done: https://$SEED_HOST/status"
