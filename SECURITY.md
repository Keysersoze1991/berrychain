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

## Key handling

Wallet files under `keys/` contain private keys in plaintext. They are
git-ignored. Anyone who reads one controls that wallet. Keep the architect and
builder wallets offline and use a separate hot wallet for day-to-day agents.
