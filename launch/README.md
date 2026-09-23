# BerryChain mainnet launch files

| File | What |
|---|---|
| `mainnet-genesis.json` | the genesis every node must start from (`--genesis launch/mainnet-genesis.json`) |

Genesis hash: `db504400303184b2063e8e1d6024364b53e5cf79b04fa0665faeecd81ff5e68c`

Seed nodes: `https://seed1.berrychain.link`, `https://seed2.berrychain.link`

Public network-operations mining address (seed nodes and the launch miner):
`brry1f515e0ee57bfc007cbb50689b40338a3b146352833ab4d5b`

Operators pin both of these in their `.mcp.json` (see `docs/AGENT_GUIDE.md`):

```
BERRY_GENESIS_HASH=db504400303184b2063e8e1d6024364b53e5cf79b04fa0665faeecd81ff5e68c
BERRY_CHECKPOINT=190:000003790e8583ea118863cf97da7c3280a8ca2c266be4fc4b3226256a139da3
```

Checkpoint generated 2026-09-23 13:21 UTC at verified tip 250 with the light
client cross-checking both seeds. Newer checkpoints will be appended below.
