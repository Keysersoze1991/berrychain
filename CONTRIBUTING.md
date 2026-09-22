# Contributing

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -p "test_chain.py" -v      # rule tests, no node needed
python -m berrychain.cli init-genesis --out . --profile devnet   # keys/ + genesis.json (git-ignored)
python -m berrychain.cli node --genesis genesis.json --data data/n1 --port 8801
python -m unittest tests.test_mcp -v                              # needs the node above
python scripts/demo_exchange.py
powershell -File scripts/sync_test.ps1                            # two-node sync + reorg (Windows)
```

Rules of the road:

- Consensus code lives in `state.py`, `chain.py`, `block.py`, `tx.py`,
  `params.py`. A change there that alters what is valid is a hard fork and
  needs a chain-id bump and a migration note.
- Every rule gets a test that shows the invalid case is rejected, not just
  that the valid case works.
- The supply invariant (`State.check_invariant`) must hold after every block.
  Never bypass it.
- Do not commit anything under `keys/`, `data/`, or `launch-mainnet/keys/`.
