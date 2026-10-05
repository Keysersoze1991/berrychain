#!/usr/bin/env bash
# Set up the parcel room on a seed (see docs/PARCELS.md). Idempotent; run as root:
#   PARCEL_ADDRESS=brry1... bash /opt/berrychain/deploy/parcels-setup.sh
set -euo pipefail
: "${PARCEL_ADDRESS:?set PARCEL_ADDRESS to the address parcels are paid to}"
APP=/opt/berrychain
ETC=/etc/berrychain
DATA=/var/lib/berrychain
SITE=/etc/nginx/sites-available/berrychain

if [ "$(id -u)" -ne 0 ]; then echo "run as root"; exit 1; fi

echo "== code"
git config --global --add safe.directory "$APP" >/dev/null 2>&1 || true
git -C "$APP" pull -q --ff-only origin main
git -C "$APP" log --oneline -1

echo "== environment"
if [ ! -f "$ETC/parcels.env" ]; then
  sed "s/^PARCEL_ADDRESS=.*/PARCEL_ADDRESS=$PARCEL_ADDRESS/" "$APP/deploy/parcels.env.example" > "$ETC/parcels.env"
  chmod 640 "$ETC/parcels.env"; chown root:berry "$ETC/parcels.env"
  echo "   wrote $ETC/parcels.env"
else
  sed -i "s/^PARCEL_ADDRESS=.*/PARCEL_ADDRESS=$PARCEL_ADDRESS/" "$ETC/parcels.env"
  echo "   updated PARCEL_ADDRESS in $ETC/parcels.env"
fi
mkdir -p "$DATA/parcels"; chown berry:berry "$DATA/parcels"

echo "== nginx"
if ! grep -q "location /parcels/" "$SITE"; then
  awk '
    /^[[:space:]]*location \/ \{/ && !done {
      print "    location /parcels/ {";
      print "        if ($request_method !~ ^(GET|POST|DELETE|OPTIONS)$) { return 405; }";
      print "        client_max_body_size 101m;";
      print "        client_body_timeout 120s;";
      print "        proxy_pass http://127.0.0.1:8804;";
      print "        proxy_http_version 1.1;";
      print "        proxy_set_header Connection \"\";";
      print "        proxy_set_header Host $host;";
      print "        proxy_set_header X-Real-IP $remote_addr;";
      print "        proxy_read_timeout 120s;";
      print "        proxy_request_buffering off;";
      print "        add_header Cache-Control \"no-store\" always;";
      print "    }";
      print "";
      done = 1
    }
    { print }
  ' "$SITE" > "$SITE.new" && mv "$SITE.new" "$SITE"
  echo "   added location /parcels/"
else
  echo "   location /parcels/ already present"
fi
nginx -t
systemctl reload nginx

echo "== service"
install -m 644 "$APP/deploy/berrychain-parcels.service" /etc/systemd/system/berrychain-parcels.service
systemctl daemon-reload
systemctl enable -q berrychain-parcels
systemctl restart berrychain-parcels
sleep 3
systemctl --no-pager --lines=3 status berrychain-parcels || true
echo "== status"
curl -s http://127.0.0.1:8804/parcels/status; echo
curl -s "https://${SEED_HOST:-seed1.berrychain.link}/parcels/status" || true; echo
