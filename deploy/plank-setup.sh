#!/usr/bin/env bash
# Set up Walk the Plank (the daily trivia dive) on a seed. Idempotent; run as root:
#   bash /opt/berrychain/deploy/plank-setup.sh
# Copies the model API key line from /etc/berrychain/agent.env so unknown answers can be judged.
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
"$APP/.venv/bin/python" -c "import anthropic" 2>/dev/null || "$APP/.venv/bin/pip" install -q "anthropic>=1"

echo "== environment"
if [ ! -s "$ETC/plank.env" ]; then
  cp "$APP/deploy/plank.env.example" "$ETC/plank.env"
fi
if [ -s "$ETC/agent.env" ] && grep -q '^ANTHROPIC_API_KEY=sk-' "$ETC/agent.env"; then
  key_line=$(grep '^ANTHROPIC_API_KEY=' "$ETC/agent.env" | head -1)
  grep -v '^ANTHROPIC_API_KEY=' "$ETC/plank.env" > "$ETC/plank.env.new"
  printf '%s\n' "$key_line" >> "$ETC/plank.env.new"
  mv "$ETC/plank.env.new" "$ETC/plank.env"
  echo "   judge: key copied from agent.env"
else
  echo "   judge: no key in agent.env, only listed answers will count"
fi
chmod 640 "$ETC/plank.env"; chown root:berry "$ETC/plank.env"
mkdir -p "$DATA/plank"; chown berry:berry "$DATA/plank"; chmod 700 "$DATA/plank"

echo "== nginx"
if ! grep -q "location /plank/" "$SITE"; then
  awk '
    /^[[:space:]]*location \/ \{/ && !done {
      print "    location /plank/ {";
      print "        if ($request_method !~ ^(GET|POST|OPTIONS)$) { return 405; }";
      print "        client_max_body_size 4k;";
      print "        proxy_pass http://127.0.0.1:8805;";
      print "        proxy_http_version 1.1;";
      print "        proxy_set_header Connection \"\";";
      print "        proxy_set_header Host $host;";
      print "        proxy_set_header X-Real-IP $remote_addr;";
      print "        proxy_read_timeout 30s;";
      print "        add_header Cache-Control \"no-store\" always;";
      print "    }";
      print "";
      done = 1
    }
    { print }
  ' "$SITE" > "$SITE.new" && mv "$SITE.new" "$SITE"
  echo "   added location /plank/"
else
  echo "   location /plank/ already present"
fi
nginx -t
systemctl reload nginx

echo "== service"
install -m 644 "$APP/deploy/berrychain-plank.service" /etc/systemd/system/berrychain-plank.service
systemctl daemon-reload
systemctl enable -q berrychain-plank
systemctl restart berrychain-plank
sleep 3
systemctl is-active berrychain-plank
curl -s http://127.0.0.1:8805/plank/status; echo
echo "== done: https://$(hostname -f 2>/dev/null || echo seed1.berrychain.link)/plank/status"
