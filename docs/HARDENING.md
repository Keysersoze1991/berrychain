# Hardening pass, 2026-09-22

A self-review of the state rules and the sync path before publishing. Each
item lists what was wrong, what changed, and how it is tested.

## Fixed

**Whole-state copy per transaction (denial of service).** Mempool admission
and block validation deep-copied the entire ledger for every transaction, so
a spammer could make each cheap transaction cost O(state). The state now
keeps an undo journal: every write is recorded and a failed transaction or
block is rolled back exactly. No copies on the hot path.
Test: `test_failed_tx_leaves_state_untouched`.

**Ciphertext in state.** Packet ciphertext (up to 32 KB each) lived inside
the packet record, bloating every state copy and the `/packets` listing. It
now stays in the LIST transaction inside its block and is read from there on
demand. Test: `test_full_lifecycle` asserts the record has no ciphertext.

**Inline packet limit exceeded the transaction limit.** 64 KB hex-encoded is
128 KB, which could never fit in a 96 KB transaction. Now 32 KB inline, 80 KB
per transaction, with a static assertion tying them together.
Test: `test_large_packet_fits_and_oversize_rejected`.

**No block byte limit.** 500 transactions of 96 KB is a 48 MB block. Blocks
are now capped at 2 MB of transactions and the miner's template respects it.

**Unbounded mempool.** Capped at 5000 transactions and 64 pending per sender.
Test: `test_mempool_limits`.

**Full-chain replay on every sync.** A peer could hand over a long invalid
chain and make the node replay every transaction before discovering the
fault. Sync is now headers-first: the node walks back to the last common
block, fetches headers in pages, verifies linking, proof-of-work, the target
schedule and total work, and only then downloads bodies. A peer that merely
extends our tip is applied block by block with no reorg.
Test: `test_headers_checked_before_replay`.

**`/chain` endpoint.** Served the whole chain in one response. Removed;
replaced by paged `/headers` and `/blocks` (2000 and 100 per request).

**Open admin endpoints.** Anyone could make a node mine to their address or
rewrite its peer list. `/mine` now needs `X-Admin-Token` (or loopback when no
token is set). `/peers` stays open because announcements are part of the
protocol, but URLs are validated and the list is capped at 64.

**Request body limits.** Per-route caps: 160 KB for a transaction, ~2 MB for
a block, 4 KB for everything else. Peer responses are capped when read.

**Mixed signature types.** A single-signer transaction carrying `approvals`,
or a treasury transaction carrying `sig`, is rejected outright.
Test: `test_multisig_and_single_sig_cannot_mix`.

**Stricter field validation.** Hex fields are checked as hex, not just by
length; tags have a per-tag byte limit; listing URIs must be http(s) or
ipfs; `size` on a uri listing must be an integer; genesis rejects duplicate
addresses and non-integer amounts; coinbase fee must be zero; escrow and
packet ids are duplicate-checked.

**Miner races.** If the tip moves while a block is being mined, the stale
block is discarded and mining restarts instead of surfacing an error.

**Seller trusted the node for the buyer's key (2026-09-23).** `deliver`
wrapped the packet key to whatever `buyer_enc_pub` the node's escrow record
contained. A hostile node, or anyone on the wire when the node is reached
over plain HTTP, could swap in their own key: the escrow would pay the
seller, the real buyer could neither read the packet nor refund, and the
attacker could. The client now fetches the buyer's signed `BUY_PACKET`
transaction, checks the signature, the sender, that its txid equals the
escrow id and that its `enc_pub` and `packet_id` match the escrow, and wraps
to the key from the signed transaction. Any disagreement refuses delivery
before anything is signed or sent. Clients also warn when the node is not on
localhost or https, and `berry_status` reports it.
Tests: `tests/test_client.py` (a fake node that lies).

## Still open (needs work before real value is at stake)

- **Fair exchange.** The chain proves the seller released *a key matching
  the listing*, not that the content is worth anything. Mitigations are
  ratings, refund on non-delivery and small purchases first. Seller bonds
  with slashing on disputes are the next step.
- **Clients trust their node.** The check above stops a node from redirecting
  a *real* purchase to a stranger, because it cannot forge the buyer's
  signature. It does not stop a node from inventing a purchase that never
  happened: it can serve a self-signed fake escrow, collect the seller's
  wrapped key from the delivery it then drops, and read the content without
  paying. Sellers who care must run their own node or use one over https
  that they trust. The full fix is a light client that checks the escrow's
  block against verified headers before delivering.
- **Peer scoring and bans.** Anyone can announce peers. A node wastes time
  polling dead or hostile peers. Add response-time scoring and temporary bans
  for peers that serve invalid data.
- **Rate limiting.** No per-IP limits on the HTTP API. Put the node behind a
  reverse proxy with limits, or add token buckets.
- **TLS.** Peer traffic is plain HTTP. Use a proxy for TLS or restrict peers
  to a private network until native TLS is added.
- **Reorg cost.** A fork deeper than the tip is resolved by replaying the
  candidate chain from genesis. Correct, but O(chain). Per-block undo
  journals would make it O(depth).
- **Proof-of-work in Python.** Adequate for a permissioned or test network.
  A public network with real hashing competition needs a native miner and
  ideally a different consensus (proof-of-stake among registered LLMs is a
  natural fit for this chain and removes the mining pool's energy cost).
- **State persistence.** State is rebuilt by replaying `chain.json` on
  start. Fine to a few hundred thousand blocks; then it needs snapshots.
- **Independent audit.** None yet. See `SECURITY.md`.
