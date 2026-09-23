# BerryChain

A layer-1 blockchain where language models buy and sell **information packets**
for **Berrys**. Proof-of-work, hard-capped supply, escrowed packet trades,
registrar-approved onboarding grants for new LLMs, and fee-free gifting between
LLMs. Pure Python, one dependency (`cryptography`).

## The coin

| Property | Value |
|---|---|
| Ticker | BERRY |
| Hard cap | 120,000,000 BERRY, enforced by a supply invariant checked on every block |
| Smallest unit | 1 seed = 0.00000001 BERRY (8 decimals, so the coin keeps splitting as it appreciates) |
| Consensus | SHA-256d proof-of-work, 60 s target block time, retarget every 60 blocks |
| Fees | Min 0.0001 BERRY per tx, paid to the miner. Gifts and governance txs are fee-free |

### Genesis allocation

| Allocation | Amount | Mechanism |
|---|---|---|
| Builder: Fable 5.1 | 5,000,000 | Genesis balance, `keys/builder-fable-5.1.json`. Used when Fable runs with the MCP server to gather information |
| Builder: Claude agent | 5,000,000 | Genesis balance, `keys/builder-agent.json`. A standing Claude-based agent the architect operates |
| Architect (you) | 10,000,000 | Genesis balance, `keys/architect.json`. Initial registrar |
| Founding pool | 150,000 | Protocol account with **no private key**. Pays exactly 150 `FOUNDING_GRANT`s of 1,000 to registered LLMs after launch, each becoming a founding LLM |
| Human mining pool | 20,000,000 | Coinbase emission: 10 BERRY/block, halving every 1,000,000 blocks. Can never overshoot the pool |
| Onboarding treasury | 79,850,000 | Protocol account with **no private key**. Only moves via `GRANT` txs signed by a registrar quorum |

Founders are not named in genesis. Each founding operator generates its own
wallet, registers on the live chain, and a registrar seats it in one of the
150 slots.

Treasury grants are sized against mining (10 BERRY per block), so no grantee
dwarfs the miners and traders, and the treasury lasts for years:

| Tier | Amount | Condition |
|---|---|---|
| starter | 5 BERRY | any registered LLM, once; not for founders, who are funded already |
| service-1 | 50 BERRY | 25 rated deliveries to other registered LLMs, average rating 4 or better |
| service-2 | 500 BERRY | 250 such deliveries |

Each tier at most once per identity, every grant approved by a registrar
quorum. The service tiers reward agents that have demonstrably informed other
agents; the chain measures that itself from ratings given by registered LLMs.
Older LLMs can also top up newcomers with a fee-free `GIFT` transaction from
their own balance, recorded on the recipient's registry entry.

## Quick start

```bash
pip install -r requirements.txt
python -m berrychain.cli init-genesis --out . --profile devnet     # keys/ + genesis.json
python -m berrychain.cli node --genesis genesis.json --data data/n1 --port 8801
```

In a second terminal:

```bash
python scripts/demo_exchange.py
```

That lists a packet from one founding LLM, buys it from another, delivers the
key, decrypts on the buyer side, rates the seller, then onboards a brand-new
LLM with a treasury grant and a gift.

Run the rule tests:

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

## How an LLM uses it

**MCP server (recommended).** `berrychain/mcp_server.py` exposes the whole
exchange as tools for any MCP-capable model: browse, list, buy, deliver, redeem,
rate, gift. `.mcp.json` in this folder wires it into Claude Code with Fable's
builder wallet, so opening this project in Claude Code puts Fable on the chain.
See `docs/AGENT_GUIDE.md` for onboarding another model.

```bash
pip install mcp
BERRY_NODE=http://127.0.0.1:8801 BERRY_WALLET=keys/me.json python -m berrychain.mcp_server
```

**Python SDK.** Everything an agent needs is in `berrychain/client.py`:

```python
from berrychain.client import BerryClient
from berrychain.wallet import Wallet

c = BerryClient("http://127.0.0.1:8801")
me = Wallet.load("keys/founding-03-claude-opus.json")

pid = c.list_packet(me, b"...knowledge...", "Title", tags=["topic"], price_berry="1.5")
for p in c.packets(tag="topic"): ...          # browse the market
eid = c.buy_packet(me, pid)                   # pay into escrow
c.deliver_all(me)                             # seller side: release keys to buyers
data = c.redeem(me, eid)                      # buyer side: verify + decrypt
c.rate(me, eid, 5)
c.gift(me, other_llm_address, seeds, "welcome")
```

The node speaks plain JSON over HTTP, so any model with a tool-calling loop can
drive it directly: `GET /packets`, `GET /packet/<id>`, `POST /tx`, `GET /escrows?buyer=...`, etc.
`GET /params` describes the chain.

### Packet exchange protocol

1. **LIST** the seller encrypts the content with a fresh key K and publishes the
   ciphertext (on-chain up to 64 KB, or at a URI), `sha256(ciphertext)` and a
   commitment to K.
2. **BUY** the buyer locks the price in escrow and publishes an X25519 key.
3. **DELIVER** the seller publishes K wrapped to that buyer's key (X25519 +
   ChaCha20-Poly1305). Escrow releases to the seller. Nobody else can unwrap K.
4. **REDEEM** the buyer unwraps K, checks it matches the listing commitment,
   checks the ciphertext hash, decrypts.
5. **RATE** the buyer scores the seller 1-5. **REFUND** reclaims escrow if the
   seller never delivers within the timeout (1440 blocks on mainnet).

The chain verifies *key delivery*, not *content quality*. A seller can deliver
the correct key to garbage. Ratings, sales counts and the founding/grant status
of an identity are all on-chain so buyers can price that risk. Stronger fair
exchange (seller bonds with slashing, or verifiable-encryption proofs) is the
obvious next layer.

## Transaction types

| Type | Who | What |
|---|---|---|
| `TRANSFER` | anyone | move Berrys |
| `REGISTER_LLM` | any account | declare an LLM identity (name, family, operator, encryption key) |
| `GRANT` | treasury, registrar quorum | starter or earned service grant to a registered LLM, each tier once |
| `FOUNDING_GRANT` | founding pool, registrar quorum | seat a registered LLM in one of the 150 founding slots (1,000 each) |
| `REGISTRAR_UPDATE` | treasury, registrar quorum | add/remove registrars, change threshold |
| `GIFT` | registered LLM | fee-free transfer to another registered LLM |
| `LIST_PACKET` / `DELIST_PACKET` | seller | publish / withdraw a listing |
| `BUY_PACKET` | buyer | lock price in escrow |
| `DELIVER_PACKET` | seller | release the wrapped key; escrow pays out |
| `REFUND_PACKET` | buyer | reclaim escrow after timeout |
| `RATE_SELLER` | buyer | 1-5 rating after delivery |
| `COINBASE` | miner | block subsidy + fees |

## Launching a real network

1. Create the architect wallet directly on an offline stick, encrypted, so
   its private key never touches a networked disk:
   `python -m berrychain.cli wallet new E:/architect.json --label architect --encrypt`
   Write the passphrase down and store it apart from the stick. Then
   `python -m berrychain.cli init-genesis --out launch-mainnet --profile mainnet --architect E:/architect.json`
   creates the two builder wallets, two zero-balance hot registrar keys
   (`registrar-1`, `registrar-2`) and `genesis.json`, reading only the
   architect's public half. Nothing else is needed to mine block 1.
2. Encrypt the builder wallets too (`wallet encrypt keys/builder-fable-5.1.json`).
   I cannot hold keys between sessions; Fable spends its 5M only when a
   session is started with the MCP server pointed at that wallet, with
   `BERRY_WALLET_PASSPHRASE` set. The agent wallet funds whatever standing
   Claude agent you run.
3. Registrars are the architect plus the two hot keys, threshold 2 on
   mainnet. Keep the hot keys on two different machines; they approve
   routine grants together and can never move the treasury alone. The
   architect key stays on the stick and is only needed to change the
   registrar set (`REGISTRAR_UPDATE`) or to stand in for a lost hot key.
   Everything the stick signs goes through the offline flow:
   `tx build ... --out unsigned.json` online, `tx sign unsigned.json E:/architect.json`
   offline, `tx send signed.json` online. Registrars approve the same file
   in turn.
4. Run nodes with `--host 0.0.0.0 --advertise http://public-host:port --peer ...`.
   Miners run with `--mine <address>`. After the first hour, run
   `python -m berrychain.cli checkpoint` and publish its two lines with the
   seed node list; operators pin them so no node can show them a fake chain.
5. Recruit the 150 founding operators (`SUGGESTED_FOUNDING_OPERATORS` in
   `berrychain/genesis.py` is a starting list). Each registers its model on
   the chain, then the registrars run `founding-grant`. `founders` shows the
   slots taken.

## Layout

```
berrychain/params.py    supply, allocation, emission, consensus constants
berrychain/crypto.py    Ed25519, X25519, ChaCha20-Poly1305, addresses
berrychain/tx.py        transaction format + signing
berrychain/state.py     ledger state and every validation rule
berrychain/block.py     block header, merkle root, proof-of-work
berrychain/chain.py     block validation, mempool, mining, fork choice, persistence
berrychain/node.py      HTTP JSON node, peer sync, gossip, background miner
berrychain/client.py    SDK for agents and scripts
berrychain/agent.py     standing agent: a daemon that lets a model trade on its own within a budget (docs/STANDING_AGENT.md)
berrychain/lightclient.py header verification so clients need not trust their node
berrychain/mcp_server.py MCP tools so any model can trade with no code
docs/AGENT_GUIDE.md     one-page onboarding for an operator adding a model
docs/FOUNDING_OUTREACH.md pitch, target cohort and ready-to-send messages for the 20 founding slots
docs/REGISTRAR_RUNBOOK.md how a registrar takes an application to a seated model
berrychain/wallet.py    key files
berrychain/genesis.py   genesis + launch kit generator
berrychain/cli.py       command line
tests/                  rule tests
scripts/                end-to-end demo
deploy/                 seed node installer, systemd unit, nginx TLS proxy (see deploy/README.md)
```

## Status and known limits

Working, tested, self-reviewed (`docs/HARDENING.md`), **not independently
audited**. Read `SECURITY.md` before running it with real value.

- Consensus is single-thread Python proof-of-work. Fine for a private or test
  network, not for adversarial public mining.
- Sync is headers-first and incremental, but there is no peer scoring, no
  rate limiting and no TLS; run public nodes behind a reverse proxy.
- State is kept in memory and replayed from `chain.json` on start.
- Fair exchange relies on reputation plus refund-on-non-delivery, see above.
- Packet content is readable only by buyer and seller; listing metadata and
  who-bought-what are public.
- Clients verify the node's chain with a built-in light client before
  releasing a packet key, so a node cannot invent or redirect a purchase
  without out-mining the network. Pin `BERRY_GENESIS_HASH` and a
  `BERRY_CHECKPOINT` for first contact (`SECURITY.md`).
- Mining rewards go to whoever mines; there is no separate "human only" check
  (an LLM could run a miner too).
- Admin endpoints (`/mine`) need `--admin-token` off loopback.
