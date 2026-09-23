#!/usr/bin/env bash
# Assemble and exec the seed node command from the environment
# (/etc/berrychain/node.env under systemd). Kept out of the unit file so no
# systemd variable expansion is involved.
#
#   SEED_HOST=seed1.example PEERS="https://seed2.example,https://seed3.example" \
#   MINER_ADDRESS=brry1... deploy/run-node.sh [--dry-run]
#
# Overrides for local testing: PYTHON, GENESIS, DATA, PORT.
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PYTHON:-$HERE/.venv/bin/python}"
GENESIS="${GENESIS:-$HERE/genesis.json}"
DATA="${DATA:-/var/lib/berrychain}"
PORT="${PORT:-8801}"
: "${SEED_HOST:?SEED_HOST must be set to the public DNS name of this server}"

args=(-m berrychain.cli node --genesis "$GENESIS" --data "$DATA"
      --host 127.0.0.1 --port "$PORT" --advertise "https://$SEED_HOST")
IFS=',' read -r -a peers <<< "${PEERS:-}"
for p in "${peers[@]}"; do
  p="${p// /}"
  if [ -n "$p" ]; then args+=(--peer "$p"); fi
done
if [ -n "${MINER_ADDRESS:-}" ]; then args+=(--mine "$MINER_ADDRESS"); fi

if [ "${1:-}" = "--dry-run" ]; then
  printf '%q ' "$PY" "${args[@]}"; echo
  exit 0
fi
cd "$HERE"
exec "$PY" "${args[@]}"
