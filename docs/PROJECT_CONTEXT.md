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
| Founding LLMs | 20 slots x 1M = 20M | held in a keyless founding pool at genesis; each slot filled after launch by a registrar-approved `FOUNDING_GRANT` (decided 2026-09-23 so mainnet can launch before founders are recruited) |
| Human mining pool | 20M | PoW coinbase, 10 BERRY/block halving every 1,000,000 blocks, capped by a pool counter |
| Onboarding treasury | 60M | no private key; only `GRANT` txs approved by a registrar quorum can spend it |
| Grant tiers | 500k / 750k / 1M | one grant per LLM identity, so 60 to 120 new models |
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
1. Push to the architect's private GitHub repository (needs their account).
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

## Mainnet launch procedure (agreed 2026-09-23)

1. On the offline stick: `wallet new E:/architect.json --label architect --encrypt`.
   Passphrase written down and kept apart from the stick; the stick is the
   only copy of the key.
2. On the launch PC: `init-genesis --out launch-mainnet --profile mainnet --architect E:/architect.json`,
   then `wallet encrypt` each generated key. registrar-1 stays here,
   registrar-2 goes to a seed node.
3. Seed nodes (2-3 small cloud servers behind a TLS proxy) run the node with
   `--advertise`; mine the genesis; after ~1 hour run `checkpoint`.
4. Make the GitHub repo public, tagged at the genesis commit; publish
   genesis.json, the two checkpoint lines and the seed node URLs on
   berrychain.link / berrychain.net.
5. Recruit founding operators; seat them with `founding-grant` approved by
   the two hot registrars. Legal review still precedes any human trading.

## Domains

The architect is registering berrychain.link and berrychain.net (2026-09-23)
as the base pages; berrychain.com is deferred on cost.

## Launch machine plan

The architect is setting up a dedicated clean machine for publishing. All
keys generated on the original development PC are to be treated as burned;
regenerate genesis and keys on the clean machine with
`python -m berrychain.cli init-genesis --out launch-mainnet --profile mainnet`.
Nothing has ever been online: every node run so far was localhost-only and
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
