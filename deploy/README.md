# Seed node deployment

One seed node = one small Linux server (1 vCPU, 1 GB RAM, 20 GB disk is
plenty) running the BerryChain node behind nginx with TLS. Two or three of
them, peered with each other, make the network reachable. Nothing here needs
Docker.

Tested target: Ubuntu 22.04 / 24.04 LTS.

## What each seed does

- Runs `berrychain.cli node` bound to localhost only.
- nginx terminates TLS (Let's Encrypt), rate-limits per IP, caps request
  sizes to the protocol maxima, and hides the admin endpoint from the world.
- Optionally mines, so the chain keeps producing blocks before any outside
  miner shows up. Rewards go to `MINER_ADDRESS`; decide whose that is and
  say so publicly.
- Holds **no valuable key**. `registrar-2` may live on one seed so grants can
  be approved from two machines; it holds no coins.

## Steps per server

1. Point a DNS name at the server: `seed1.berrychain.link`, `seed2...`.
2. As root:

   ```bash
   curl -fsSL https://raw.githubusercontent.com/Keysersoze1991/berrychain/main/deploy/install.sh -o install.sh
   SEED_HOST=seed1.berrychain.link \
   PEERS="https://seed2.berrychain.link,https://seed3.berrychain.link" \
   MINER_ADDRESS=brry1... \
   ADMIN_EMAIL=you@example.com \
   bash install.sh
   ```

   The script installs Python, nginx and certbot, creates a `berry` system
   user, clones the repository into `/opt/berrychain`, installs the
   dependencies in a venv, writes the systemd unit and the nginx site, and
   requests the certificate.
3. Copy the launch `genesis.json` to `/opt/berrychain/genesis.json` (the
   script stops and tells you if it is missing) and start the node:

   ```bash
   systemctl start berrychain-node && journalctl -u berrychain-node -f
   ```

4. Check from anywhere: `curl https://seed1.berrychain.link/status`.

## Files

| File | Purpose |
|---|---|
| `install.sh` | idempotent installer; re-run to update the code (`git pull` + restart) |
| `run-node.sh` | builds the node command line from the environment file; `--dry-run` shows it |
| `berrychain-node.service` | systemd unit, sandboxed; environment in `/etc/berrychain/node.env` |
| `nginx-seed.conf` | TLS proxy, rate limits, body caps, `/mine` blocked |
| `node.env.example` | the environment file the unit reads |

## After the first hour of blocks

On any machine with the client:

```bash
BERRY_NODE=https://seed1.berrychain.link python -m berrychain.cli checkpoint
```

Publish the two lines it prints together with the seed URLs. Operators put
them in their `.mcp.json` (see `docs/AGENT_GUIDE.md`).

## Updating

```bash
bash /opt/berrychain/deploy/install.sh   # same env vars; pulls, reinstalls, restarts
```

Consensus changes are hard forks and need a chain id bump; do not roll
those out this way.

## While the repository is private

The installer clones with git. Until the repo is public, ship it as a git
bundle instead of giving the servers GitHub credentials:

```bash
git bundle create berrychain.bundle main            # on the launch PC
scp berrychain.bundle root@seed1.berrychain.link:/root/
```

then on the server pass the bundle as the repository:

```bash
REPO=/root/berrychain.bundle SEED_HOST=seed1.berrychain.link ... bash install.sh
```

Re-running the installer with a fresh bundle updates the code the same way.
