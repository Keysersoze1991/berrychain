"""
Light client: header-only verification of a node's chain.

A client that believes its node can be lied to. This module lets a client
check for itself that a transaction is buried under real proof-of-work on the
heaviest chain it has ever seen, using only block headers and one block:

  1. On first contact, reconstruct the genesis block from the node's block 0
     and pin its hash (or require BERRY_GENESIS_HASH to match).
  2. Fetch headers, verify every one (linking, hash, proof-of-work, difficulty
     schedule, timestamps) with the same rules a full node applies.
  3. Keep the verified header chain on disk. Never move to a lighter chain.
     Optionally refuse any chain that does not contain a pinned checkpoint.
  4. To verify a transaction: fetch its block, check the block hashes to the
     verified header at that height, check the merkle root, check the
     transaction is in it, and require a minimum number of confirmations.

What this defeats: a node inventing a purchase, or hiding the real chain
behind a cheap fork. To fool a client that has already seen the real chain,
an attacker must out-mine the network. What remains: the very first sync
(trust on first use) unless a checkpoint or genesis hash is pinned, and the
usual proof-of-work assumption.

Pass extra `verify_nodes` and the client syncs headers from each of them
too, so the "heaviest chain seen" is the heaviest any of them shows.
"""

from __future__ import annotations

import json
import os
import time

from . import block as B, params, tx as T
from .chain import BlockError, Chain

STEP_HEADERS = params.MAX_HEADERS_PER_REQUEST


class VerifyError(Exception):
    """The node's story does not check out. Safe to show to users."""


class LightClient:
    def __init__(self, path: str | None = None, checkpoint: tuple[int, str] | None = None,
                 genesis_hash: str | None = None):
        self.path = path
        self.checkpoint = checkpoint
        self.genesis_hash = genesis_hash
        self.headers: list[dict] = []
        self.genesis: dict | None = None
        self._chain: Chain | None = None
        if path and os.path.exists(path):
            with open(path) as f:
                d = json.load(f)
            self.genesis, self.headers = d["genesis"], d["headers"]
            self._chain = Chain(self.genesis)
            if self.headers[0]["hash"] != self._chain.blocks[0]["hash"]:
                raise VerifyError(f"stored headers in {path} do not match their genesis")

    # ----------------------------------------------------------- helpers
    @property
    def height(self) -> int:
        return len(self.headers) - 1

    @property
    def tip(self) -> dict | None:
        return self.headers[-1] if self.headers else None

    def work(self) -> int:
        return Chain.work_of(self.headers) if self.headers else -1

    @property
    def profile(self) -> dict:
        return self._chain.profile if self._chain else {}

    def save(self) -> None:
        if not self.path:
            return
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"genesis": self.genesis, "headers": self.headers}, f)
        os.replace(tmp, self.path)

    # --------------------------------------------------------- bootstrap
    def _bootstrap(self, node) -> None:
        """Rebuild the genesis block from the node's block 0 and pin its hash."""
        st = node.get("/status")
        b0 = node.get("/block/0")
        try:
            p = b0["txs"][0]["payload"]
            genesis = {
                "profile": st["profile"], "timestamp": b0["timestamp"], "message": p.get("message", ""),
                "allocations": p["allocations"], "registrars": p["registrars"],
                "registrar_threshold": p.get("registrar_threshold", 1),
            }
            chain = Chain(genesis)
        except (KeyError, TypeError, IndexError, BlockError, Exception) as e:
            raise VerifyError(f"node's genesis block is malformed: {e}") from None
        ghash = chain.blocks[0]["hash"]
        if ghash != b0.get("hash"):
            raise VerifyError("node's genesis block does not hash to what it claims")
        if self.genesis_hash and ghash != self.genesis_hash:
            raise VerifyError(f"node's genesis {ghash[:12]} is not the pinned genesis {self.genesis_hash[:12]}")
        self.genesis, self._chain, self.headers = genesis, chain, [dict(chain.headers(0, 0)[0])]

    # -------------------------------------------------------------- sync
    def sync(self, node, now: int | None = None) -> bool:
        """Bring the verified header chain up to the node's tip. Returns True
        if our best chain changed. Raises VerifyError if the node presents an
        invalid chain, a lighter chain than our best, or one without the
        checkpoint."""
        if self._chain is None:
            self._bootstrap(node)
        if self.genesis_hash and self.headers[0]["hash"] != self.genesis_hash:
            raise VerifyError("stored genesis is not the pinned genesis")
        now = int(time.time()) if now is None else now
        st = node.get("/status")
        peer_h = int(st.get("height", 0))

        # last block we share with the node, walking back in doubling steps
        common = None
        h, step = min(self.height, peer_h), 1
        tried_zero = False
        while True:
            hdrs = node.get(f"/headers?from={h}&to={h}").get("headers") or []
            if hdrs and hdrs[0].get("hash") == self.headers[h]["hash"]:
                common = h
                break
            if h == 0:
                tried_zero = True
                break
            h = max(0, h - step)
            step *= 2
        if common is None:
            if tried_zero:
                where = f" stored in {self.path}" if self.path else ""
                raise VerifyError(f"node's chain does not share the genesis{where}; if this is a regenerated devnet, delete that file")
            raise VerifyError("cannot find a common block with the node")

        candidate = self.headers[:common + 1]
        lo = common + 1
        while lo <= peer_h:
            hi = min(lo + STEP_HEADERS - 1, peer_h)
            page = node.get(f"/headers?from={lo}&to={hi}").get("headers") or []
            if not page:
                break
            candidate.extend(page)
            lo = hi + 1
        try:
            for i in range(common + 1, len(candidate)):
                self._chain.check_header(candidate[i], candidate, now, upto=i)
        except BlockError as e:
            raise VerifyError(f"node served an invalid header: {e}") from None

        work = Chain.work_of(candidate)
        if work < self.work():
            hint = (f"; if you deliberately reset a devnet, delete {self.path}" if self.path and
                    str(self.profile.get("chain_id", "")).endswith("-dev") else "")
            raise VerifyError(f"node is on a lighter chain (height {len(candidate) - 1}) than the best already verified (height {self.height}){hint}")
        if work == self.work() and candidate[-1]["hash"] != self.tip["hash"]:
            raise VerifyError("node is on a different fork of equal work; keeping the chain already verified")
        if self.checkpoint:
            ch, chash = self.checkpoint
            if len(candidate) <= ch or candidate[ch]["hash"] != chash:
                raise VerifyError(f"node's chain does not contain checkpoint {ch}:{chash[:12]}")
        changed = candidate[-1]["hash"] != (self.tip or {}).get("hash")
        self.headers = candidate
        if changed:
            self.save()
        return changed

    # ----------------------------------------------------------- verify
    def verify_tx(self, node, txid: str, min_confirmations: int | None = None,
                  verify_nodes: list | None = None, now: int | None = None) -> dict:
        """Prove `txid` is in a block on the heaviest verified chain with at
        least `min_confirmations` blocks on top (the containing block counts
        as one). Returns the transaction exactly as the block carries it."""
        for extra in verify_nodes or []:
            try:
                self.sync(extra, now)
            except (VerifyError, Exception):  # noqa: BLE001  a bad helper must not block delivery
                pass
        self.sync(node, now)
        if min_confirmations is None:
            min_confirmations = int(self.profile.get("min_confirmations", 6))

        r = node.get(f"/tx/{txid}")
        if r.get("status") != "confirmed" or not isinstance(r.get("height"), int):
            raise VerifyError("transaction is not confirmed")
        h = r["height"]
        if not 0 < h <= self.height:
            raise VerifyError("transaction height is beyond the verified chain")
        blk = node.get(f"/block/{h}")
        hdr = self.headers[h]
        try:
            if B.block_hash(blk) != hdr["hash"]:
                raise VerifyError(f"block {h} served by the node is not the verified block at that height")
            ids = [T.txid(t) for t in blk["txs"]]
        except (KeyError, TypeError, ValueError) as e:
            raise VerifyError(f"block {h} is malformed: {e}") from None
        if B.merkle_root(ids) != hdr["merkle_root"]:
            raise VerifyError(f"block {h} transactions do not match its merkle root")
        if txid not in ids:
            raise VerifyError(f"transaction is not in block {h}")
        conf = self.height - h + 1
        if conf < min_confirmations:
            raise VerifyError(f"transaction has {conf} confirmation(s), {min_confirmations} required")
        return blk["txs"][ids.index(txid)]
