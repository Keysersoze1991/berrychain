#!/usr/bin/env bash
# Set up the opt-in push relay on a seed (see docs/PUSH.md). Idempotent; run as root:
#   KEY_ID=XN522VMT2C bash /opt/berrychain/deploy/push-setup.sh
# Expects the APNs key already copied to /etc/berrychain/apns.p8 (scp it first).
set -euo pipefail
: "${KEY_ID:?set KEY_ID to the ten-character APNs Key ID from the Apple portal}"
APP=/opt/berrychain
ETC=/etc/berrychain
DATA=/var/lib/berrychain
SITE=/etc/nginx/sites-available/berrychain

if [ "$(id -u)" -ne 0 ]; then echo "run as root"; exit 1; fi
if [ ! -s "$ETC/apns.p8" ]; then echo "!! $ETC/apns.p8 is missing: scp the AuthKey_*.p8 there first"; exit 1; fi

echo "== code"
git config --global --add safe.directory "$APP" >/dev/null 2>&1 || true
git -C "$APP" pull -q --ff-only origin main
git -C "$APP" log --oneline -1
"$APP/.venv/bin/pip" install -q -r "$APP/requirements.txt"

echo "== environment"
sed "s/^APNS_KEY_ID=.*/APNS_KEY_ID=$KEY_ID/" "$APP/deploy/push.env.example" > "$ETC/push.env"
chmod 640 "$ETC/push.env" "$ETC/apns.p8"
chown root:berry "$ETC/push.env" "$ETC/apns.p8"
mkdir -p "$DATA/push"; chown berry:berry "$DATA/push"

echo "== nginx"
if ! grep -q "location /push/" "$SITE"; then
  # insert the relay location just before the catch-all; works whether or not certbot has edited the file
  awk '
    /^[[:space:]]*location \/ \{/ && !done {
      print "    location /push/ {";
      print "        if ($request_method !~ ^(GET|POST)$) { return 405; }";
      print "        client_max_body_size 8k;";
      print "        proxy_pass http://127.0.0.1:8803;";
      print "        proxy_http_version 1.1;";
      print "        proxy_set_header Connection \"\";";
      print "        proxy_set_header Host $host;";
      print "        proxy_set_header X-Real-IP $remote_addr;";
      print "        proxy_read_timeout 15s;";
      print "        add_header Cache-Control \"no-store\" always;";
      print "    }";
      print "";
      done = 1
    }
    { print }
  ' "$SITE" > "$SITE.new" && mv "$SITE.new" "$SITE"
  echo "   added location /push/ ($(grep -c 'location /push/' "$SITE") block(s))"
else
  echo "   location /push/ already present"
fi
nginx -t
systemctl reload nginx

echo "== service"
install -m 644 "$APP/deploy/berrychain-push.service" /etc/systemd/system/berrychain-push.service
systemctl daemon-reload
systemctl enable -q berrychain-push
systemctl restart berrychain-push
sleep 3
systemctl --no-pager --lines=3 status berrychain-push || true
echo "== status"
curl -s http://127.0.0.1:8803/push/status; echo
curl -s "https://${SEED_HOST:-seed1.berrychain.link}/push/status" || true; echo
