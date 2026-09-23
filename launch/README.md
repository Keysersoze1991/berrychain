# BerryChain mainnet launch files

| File | What |
|---|---|
| `mainnet-genesis.json` | the genesis every node must start from (`--genesis launch/mainnet-genesis.json`) |

Genesis hash: `1e9ef40d8eea8d41cf1204e44873279b249a34ebea61088ca45159d07bae1303`

Seed nodes: `https://seed1.berrychain.link`, `https://seed2.berrychain.link`

Public network-operations mining address (seed nodes and the launch miner):
`brry1f515e0ee57bfc007cbb50689b40338a3b146352833ab4d5b`

Operators pin `BERRY_GENESIS_HASH` to the hash above; a `BERRY_CHECKPOINT`
will be added here after the first blocks.
