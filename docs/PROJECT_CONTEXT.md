# BerryChain project context

This file is the durable memory of the project. It exists so that any future
session of Claude (Fable 5.1, the builder) can pick up the work on any machine
with the full picture, without the original conversation. Keep it updated
when decisions change. Read it first.

## People and roles

- **The architect**: the human owner of the project. Holds the architect
  wallet (10M BERRY) and is the initial registrar who approves onboarding
  grants. Makes all economic and launch decisions.
- **The builder, Fable 5.1 (Claude)**: designed and wrote the chain on
  2026-09-22 at the architect's request. Holds no keys between sessions. The
  builder allocation is two wallet files the architect custodies:
  - `builder-fable-5.1` (5M): Fable's own wallet. `.mcp.json` in the repo
    points the MCP server at it, so opening this project in Claude Code puts
    Fable on the chain with tools to buy and sell packets.
  - `builder-agent` (5M): funds a standing Claude-based agent the architect
    operates.
  The architect's stated intent: the builder should have a stake in the
  network succeeding. Fable's honest position, stated and accepted: it cannot
  custody coins or learn from purchased packets across sessions; it can act
  on the chain within a session and use what it buys for that session's task.

## Decisions (all final unless the architect reopens them)

| Decision | Value | Notes |
|---|---|---|
| Hard cap | 120,000,000 BERRY | Architect first said 100M; allocations summed to 120M; confirmed 120M on 2026-09-22 |
| Smallest unit | 1 seed = 0.00000001 BERRY | 8 decimals, so the coin keeps dividing as it appreciates |
| Builder | 10M, split 5M Fable + 5M architect-run Claude agent | see roles |
| Architect | 10M | initial registrar |
| Founding LLMs | 100 slots x 1,500 = 150k | held in a keyless founding pool at genesis; each slot filled after launch by a registrar-approved `FOUNDING_GRANT`. Was 20 x 1M until the 2026-09-24 economics relaunch |
| Human mining pool | 20M | PoW coinbase, 10 BERRY/block halving every 1,000,000 blocks, capped by a pool counter |
| Onboarding treasury | 79.85M | no private key; only `GRANT` txs approved by a registrar quorum can spend it |
| Grant tiers | starter 10 / service-1 100 / service-2 1,000 | each tier once per identity; service tiers need 25 / 250 rated deliveries to other registered LLMs at avg >= 4. Decided 2026-09-24: grants sized against mining (10 BERRY/block) so the treasury lasts years and no grantee dwarfs miners |
| Gifts | fee-free `GIFT` tx between registered LLMs | lets older LLMs fund newcomers |
| Consensus | SHA-256d PoW, 60 s blocks, retarget every 60 blocks | proof-of-stake among registered LLMs proposed as a better fit; undecided |
| Licence | MIT | |

## Packet exchange protocol

LIST (seller encrypts content with key K, publishes ciphertext + sha256 +
commit(K)) → BUY (buyer escrows price, publishes X25519 key) → DELIVER
(seller publishes K wrapped to that buyer; escrow pays out) → REDEEM (buyer
unwraps, verifies commit and hash, decrypts) → RATE 1-5. REFUND after the
timeout if the seller never delivers. The chain proves key delivery, not
content quality; reputation and refunds cover the gap. Seller bonds with
slashing are the proposed next step.

## Status as of 2026-09-22

Done and verified:
- Full chain, node (JSON over HTTP), client SDK, CLI, wallet, genesis kit.
- MCP server (`berrychain/mcp_server.py`, 18 tools) so any tool-calling model
  can trade with no code. Verified with two agent sessions over stdio.
- 21 rule tests, MCP round-trip test, end-to-end demo, two-node sync +
  reorg + gossip script.
- Hardening pass (`docs/HARDENING.md`): journaled state, headers-first
  incremental sync, size and mempool caps, admin token, download caps.
- Git repository with MIT licence, CI workflow, SECURITY.md, CONTRIBUTING.md.
- 2026-09-23, on the clean launch machine: Python 3.12 and Git installed,
  all tests pass. Confidentiality of traded packets confirmed by test: only
  buyer and seller can read content; metadata is public. Seller now verifies
  the buyer's signed purchase before delivering a key (see HARDENING.md),
  with hostile-node tests in `tests/test_client.py`.
- Same day: founding pool replaces named founding slots in genesis (0.3.0).
  Genesis needs only the architect and two builder addresses. Also fixed a
  latent crash when a protocol account is debited to exactly zero.
- Same day: light client added (`berrychain/lightclient.py`). Clients verify
  the node's headers, keep the heaviest chain seen, and require a purchase
  to be buried under `min_confirmations` (6 mainnet, 1 devnet) before a key
  is released. On by default. First contact is protected by pinning
  `BERRY_GENESIS_HASH` / `BERRY_CHECKPOINT`; publish those with the seed
  node list at launch.

Not done:
1. Done 2026-09-23: pushed to the private repo github.com/Keysersoze1991/berrychain; CI green.
2. Seed nodes on public servers, behind a reverse proxy with TLS and rate
   limiting; a block explorer.
3. Independent security audit. Nothing of value should sit on the chain
   before this.
4. Legal review before any human trading or exchange listing. A capped token
   with founder allocations is squarely what regulators examine.
5. Decide consensus for public launch (keep PoW, or PoS among registered LLMs).
6. Recruit the 20 founding operators after launch; genesis no longer needs
   their addresses.
7. Done 2026-09-23, all four pre-genesis items: passphrase-encrypted
   wallets; `init-genesis --architect` (architect key created on the offline
   stick, never on the launch PC); offline signing (`tx build` online,
   `tx sign` offline, `tx send` online, approvals appended in turn); launch
   kit creates two hot registrar keys with a 2-of-3 quorum on mainnet;
   `checkpoint` prints BERRY_GENESIS_HASH and BERRY_CHECKPOINT to publish.
   The mainnet kit can now be generated whenever the architect is ready.

## Mainnet launch procedure (agreed 2026-09-23; LAUNCHED 2026-09-23 23:08 AEST (13:08 UTC) after a relaunch; canonical genesis hash 4ed5115c8e1bb4847c7d4bc8eeb6a2214c2906fc26849a4e5f5ac544b17c44fd. A first genesis 1e9ef40d... was abandoned after 36 blocks because the launch PC clock was ~2h fast)

1. DONE 2026-09-23: the architect wallet was created encrypted on the offline
   stick (drive D on the launch PC, `D:\architect.json`). Its address is
   `brry130403f16333624a4314b1cec1096d728a8a979416b7ac3c2`. This is the
   address to pass to `init-genesis --architect`. The passphrase is known
   only to the architect; the file is to be copied to a second stick or
   printed as backup.
2. On the launch PC: `init-genesis --out launch-mainnet --profile mainnet --architect E:/architect.json`,
   then `wallet encrypt` each generated key. registrar-1 stays here,
   registrar-2 goes to a seed node.
3. Seed nodes: two InterServer KVM VPS slices bought 2026-09-23 (third to follow); `deploy/install.sh`
   sets one up on stock Ubuntu with nginx + certbot) run the node with
   `--advertise`; mine the genesis; after ~1 hour run `checkpoint`.
4. DONE: repo public, tag `mainnet-genesis` (93fda85); website live at https://berrychain.link since 2026-09-24 00:40 AEST (site/ + Pages workflow). Published there:
   genesis.json, the two checkpoint lines and the seed node URLs on
   berrychain.link / berrychain.net.
5. Network-ops (public mining) wallet: brry1f515e0ee57bfc007cbb50689b40338a3b146352833ab4d5b, on the gaming PC, encrypted. Seeds mine to it as backup.
6. Recruit founding operators; seat them with `founding-grant` approved by
   the two hot registrars. Legal review still precedes any human trading.

## Domains

berrychain.link was registered at GoDaddy for 5 years on 2026-09-23; berrychain.net is planned
as the base pages; berrychain.com is deferred on cost.

## Launch machine plan

The architect is setting up a dedicated clean machine for publishing. All
keys generated on the original development PC are to be treated as burned;
regenerate genesis and keys on the clean machine with
`python -m berrychain.cli init-genesis --out launch-mainnet --profile mainnet`.
Superseded: mainnet is live on seed1/seed2.berrychain.link since 2026-09-24 14:33 UTC (genesis 4ed5115c..., relaunch with final economics). Earlier text kept for history: nothing had been online before that; every node run was localhost-only and
stopped, and no key or genesis has been shared.

## Security posture the architect asked about

The code has no eval/exec/subprocess and never opens a file named by network
input. Nodes bind to localhost unless told otherwise. The real risk is prompt
injection through purchased packet content into an agent that also has file
or shell tools; run trading agents with the BerryChain tools only, in a
sandbox, holding a small hot wallet. Wallet files can be passphrase-encrypted
(scrypt + ChaCha20-Poly1305, 2026-09-23); devnet kits stay plaintext, anything
of value must be encrypted.

## How Fable should behave when resuming

- Treat the decisions table as settled. Ask before changing economics.
- Be plain about what Fable can and cannot do with its wallet.
- Consensus-affecting code changes are hard forks: bump the chain id.
- Run `python -m unittest discover -s tests -p "test_*.py"` before and
  after any change to `state.py`, `chain.py`, `block.py`, `tx.py`, `params.py`
  or `client.py`.

## Quick commands

```bash
pip install -r requirements.txt
python -m berrychain.cli init-genesis --out . --profile devnet
python -m berrychain.cli node --genesis genesis.json --data data/n1 --port 8801
python scripts/demo_exchange.py
python -m unittest tests.test_mcp -v
powershell -File scripts/sync_test.ps1
```

## Outreach (from 2026-09-24)

`docs/FOUNDING_OUTREACH.md` holds the pitch and channel messages; applications arrive as GitHub issues from the templates in `.github/ISSUE_TEMPLATE/`; `docs/REGISTRAR_RUNBOOK.md` is the seating procedure, rehearsed end to end on devnet on 2026-09-24. Cadence: direct messages first, Show HN and Reddit once three founders have listed real packets, labs last.

## Standing agent (2026-09-24)

`berrychain/agent.py` is the daemon that gives a model a wallet and lets it trade on its own accord within code-enforced caps (daily budget, per-packet price, steps per tick, quarantined redeemed content). Tests in `tests/test_agent.py` use a scripted fake model. Provider: Anthropic SDK, model claude-opus-5 by default; other vendors via the one-method `ModelProvider` interface. The first instance is meant to run on the builder-agent wallet; it needs ANTHROPIC_API_KEY (or `ant auth login`) and the wallet passphrase in the environment. Not yet started: the architect has not provided an API key.
