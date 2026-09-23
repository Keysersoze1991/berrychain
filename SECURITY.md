# Security

BerryChain is pre-launch software. It has had an internal hardening pass
(see `docs/HARDENING.md`) but **no independent audit**. Do not put value you
cannot afford to lose on a network running this code until an audit is done.

## Reporting

Report vulnerabilities privately to the maintainers rather than in a public
issue. Include the affected file, a reproduction, and the impact (theft,
inflation, consensus split, denial of service). We aim to acknowledge within
three days.

## Scope

In scope: anything in `berrychain/` that lets someone mint coins beyond the
cap, spend coins they do not own, take escrowed funds without delivering,
spend the treasury or the founding pool without a registrar quorum, seat more
than 20 founders, split consensus between honest
nodes, or knock a node over with cheap requests.

Out of scope: the content of packets (the chain verifies key delivery, not
truthfulness), and social attacks on registrars.

## Packet confidentiality

Packet content is encrypted with a per-packet key; the key is delivered
wrapped to the buyer's X25519 key. Nodes, miners and other users see only
ciphertext. Metadata (title, tags, price, buyer and seller addresses) is
public. Whoever holds a wallet file can read everything that wallet bought
or sold, and a buyer can always pass content on.

## Node trust

Clients do not take the node's word for a purchase. Before a seller releases
a key, the client verifies the node's block headers itself (proof-of-work,
difficulty schedule, linking), keeps the heaviest chain it has ever seen,
and requires the purchase to sit in that chain under enough confirmations.
A node cannot redirect a real purchase (the buyer's signature binds it) and
cannot invent one without out-mining the network. On first contact the
client has nothing to compare against, so pin `BERRY_GENESIS_HASH` and a
published `BERRY_CHECKPOINT`, or name several `BERRY_VERIFY_NODES`. Over
plain HTTP off localhost the client warns; prefer https or your own node.

## Key handling

Wallet files under `keys/` contain private keys in plaintext. They are
git-ignored. Anyone who reads one controls that wallet. Keep the architect and
builder wallets offline and use a separate hot wallet for day-to-day agents.
