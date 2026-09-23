# BerryChain mainnet launch files

| File | What |
|---|---|
| `mainnet-genesis.json` | the genesis every node must start from (`--genesis launch/mainnet-genesis.json`) |

Genesis hash: `db504400303184b2063e8e1d6024364b53e5cf79b04fa0665faeecd81ff5e68c`

Seed nodes: `https://seed1.berrychain.link`, `https://seed2.berrychain.link`

Public network-operations mining address (seed nodes and the launch miner):
`brry1f515e0ee57bfc007cbb50689b40338a3b146352833ab4d5b`

Operators pin `BERRY_GENESIS_HASH` to the hash above; a `BERRY_CHECKPOINT`
will be added here after the first blocks.
