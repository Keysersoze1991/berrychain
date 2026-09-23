# BerryChain mainnet launch files

| File | What |
|---|---|
| `mainnet-genesis.json` | the genesis every node must start from (`--genesis launch/mainnet-genesis.json`) |

Genesis hash: `4ed5115c8e1bb4847c7d4bc8eeb6a2214c2906fc26849a4e5f5ac544b17c44fd`

Seed nodes: `https://seed1.berrychain.link`, `https://seed2.berrychain.link`

Public network-operations mining address (seed nodes and the launch miner):
`brry1f515e0ee57bfc007cbb50689b40338a3b146352833ab4d5b`

Relaunched 2026-09-23 14:33 UTC with the final economics (150 founding slots of 1,000 BERRY; starter 5 / service 50 / 500 grants, finalised 2026-09-24 without a genesis change); the earlier genesis db504400... is retired. Operators pin both of these in their `.mcp.json` (see `docs/AGENT_GUIDE.md`):

```
BERRY_GENESIS_HASH=4ed5115c8e1bb4847c7d4bc8eeb6a2214c2906fc26849a4e5f5ac544b17c44fd
BERRY_CHECKPOINT=94:000016e8e41005dc8b0bcc21f8d29a1c18a65712afac81e4c7871c6909324b8e
```

Checkpoint generated 2026-09-23 14:39 UTC at verified tip 154 with the light client cross-checking both seeds.
