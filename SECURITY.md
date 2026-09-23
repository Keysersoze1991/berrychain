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
spend the treasury without a registrar quorum, split consensus between honest
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

A client believes the node it talks to. Over https or on localhost that is
your own node; over plain HTTP on the open internet it can be anyone. The
seller verifies the buyer's signed purchase before delivering a key, so a
node cannot redirect a real purchase, but it can still fabricate one. Run
your own node, or use one you trust over https.

## Key handling

Wallet files under `keys/` contain private keys in plaintext. They are
git-ignored. Anyone who reads one controls that wallet. Keep the architect and
builder wallets offline and use a separate hot wallet for day-to-day agents.
