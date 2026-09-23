# BerryChain mainnet launch files

| File | What |
|---|---|
| `mainnet-genesis.json` | the genesis every node must start from (`--genesis launch/mainnet-genesis.json`) |

Genesis hash: `4ed5115c8e1bb4847c7d4bc8eeb6a2214c2906fc26849a4e5f5ac544b17c44fd`

Seed nodes: `https://seed1.berrychain.link`, `https://seed2.berrychain.link`

Public network-operations mining address (seed nodes and the launch miner):
`brry1f515e0ee57bfc007cbb50689b40338a3b146352833ab4d5b`

Relaunched 2026-09-24 ~14:32 UTC with the final economics (100 founding slots of 1,500 BERRY; starter 10 / service 100 / 1,000 grants); the earlier genesis db504400... is retired. Operators pin the genesis hash above as `BERRY_GENESIS_HASH`; a `BERRY_CHECKPOINT` will be added here after the first blocks.
