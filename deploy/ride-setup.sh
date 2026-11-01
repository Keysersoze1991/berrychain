#!/usr/bin/env bash
# Set up MTB Crazy's record board and referee on a seed. Idempotent; run as root:
#   bash /opt/berrychain/deploy/ride-setup.sh
# Needs Node (the referee replays runs on the game's own engine): apt-get install -y nodejs if missing.
# The Harbourmaster (berrychain-agent) pays the prizes the board queues, so restart it afterwards once.
set -euo pipefail
APP=/opt/berrychain
ETC=/etc/berrychain
DATA=/var/lib/berrychain
SITE=/etc/nginx/sites-available/berrychain

if [ "$(id -u)" -ne 0 ]; then echo "run as root"; exit 1; fi

echo "== code"
git config --global --add safe.directory "$APP" >/dev/null 2>&1 || true
git -C "$APP" pull -q --ff-only origin main
git -C "$APP" log --oneline -1
"$APP/.venv/bin/pip" install -q -r "$APP/requirements.txt"

echo "== referee"
NODE=$(command -v node || command -v nodejs || true)
if [ -z "$NODE" ]; then
  echo "   node is not installed: apt-get install -y nodejs, then run this again"; exit 1
fi
echo "   $NODE $($NODE --version)"
"$NODE" "$APP/site/ride/check.js" --courses | head -c 200; echo

echo "== environment"
if [ ! -s "$ETC/ride.env" ]; then
  sed "s#^RIDE_NODE=.*#RIDE_NODE=$NODE#" "$APP/deploy/ride.env.example" > "$ETC/ride.env"
fi
chmod 640 "$ETC/ride.env"; chown root:berry "$ETC/ride.env"
mkdir -p "$DATA/ride"; chown berry:berry "$DATA/ride"; chmod 700 "$DATA/ride"

echo "== nginx"
if ! grep -q "location /ride/" "$SITE"; then
  awk '
    /^[[:space:]]*location \/ \{/ && !done {
      print "    location /ride/ {";
      print "        if ($request_method !~ ^(GET|POST|OPTIONS)$) { return 405; }";
      print "        client_max_body_size 80k;";
      print "        proxy_pass http://127.0.0.1:8806;";
      print "        proxy_http_version 1.1;";
      print "        proxy_set_header Connection \"\";";
      print "        proxy_set_header Host $host;";
      print "        proxy_set_header X-Real-IP $remote_addr;";
      print "        proxy_read_timeout 40s;";
      print "        add_header Cache-Control \"no-store\" always;";
      print "    }";
      print "";
      done = 1
    }
    { print }
  ' "$SITE" > "$SITE.new" && mv "$SITE.new" "$SITE"
  echo "   added location /ride/"
else
  echo "   location /ride/ already present"
fi
nginx -t
systemctl reload nginx

echo "== service"
install -m 644 "$APP/deploy/berrychain-ride.service" /etc/systemd/system/berrychain-ride.service
systemctl daemon-reload
systemctl enable -q berrychain-ride
systemctl restart berrychain-ride
sleep 3
systemctl is-active berrychain-ride
curl -s http://127.0.0.1:8806/ride/status; echo
echo "== done: https://$(hostname -f 2>/dev/null || echo seed1.berrychain.link)/ride/status"
echo "   now: bash $APP/deploy/plank-setup.sh (opens the dive prize) and systemctl restart berrychain-agent (pays both)"
