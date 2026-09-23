"""
The chain: block validation, mempool, mining, fork choice and persistence.

Validation is two-phase. Header checks (linking, hash, proof-of-work, target
schedule) are cheap and run first, on any candidate chain, before a single
transaction is replayed. Only a candidate whose headers already carry more
work than ours gets its transactions applied.
"""

from __future__ import annotations

import json
import os
import threading
import time

from . import block as B, params, tx as T
from .crypto import canonical_json
from .state import State, TxError

HEADER_FIELDS = ("height", "prev_hash", "timestamp", "target", "merkle_root", "nonce", "hash")


class BlockError(Exception):
    pass


def header_of(block: dict) -> dict:
    return {k: block[k] for k in HEADER_FIELDS}


class Chain:
    def __init__(self, genesis: dict):
        self.genesis = genesis
        profile_name = genesis.get("profile", "mainnet")
        if profile_name not in params.PROFILES:
            raise BlockError(f"unknown profile {profile_name}")
        self.profile = dict(params.PROFILES[profile_name])
        self.profile_name = profile_name
        self.blocks: list[dict] = []
        self.state = State(self.profile)
        self.mempool: dict[str, dict] = {}
        self._mempool_state: State | None = None
        self.tx_index: dict[str, tuple[int, int]] = {}
        self.lock = threading.RLock()
        self._apply_genesis_block()

    # ------------------------------------------------------------- genesis
    def _genesis_block(self) -> dict:
        g = self.genesis
        payload = {
            "message": g.get("message", ""),
            "allocations": g["allocations"],
            "registrars": g["registrars"],
            "registrar_threshold": g.get("registrar_threshold", 1),
            "max_supply": params.MAX_SUPPLY,
            "mining_pool": params.ALLOC_MINING_POOL,
        }
        gtx = T.build(T.GENESIS, "genesis", 0, 0, payload, self.profile["chain_id"])
        return B.make_block(0, "00" * 32, int(g["timestamp"]), self.profile["max_target"], [gtx])

    def _apply_genesis_block(self) -> None:
        blk = self._genesis_block()
        p = blk["txs"][0]["payload"]
        self.state.apply_genesis(p["allocations"], p["registrars"], p["registrar_threshold"])
        self.blocks.append(blk)
        self.tx_index[T.txid(blk["txs"][0])] = (0, 0)
        self._mempool_state = self.state.copy()

    # ------------------------------------------------------------ queries
    @property
    def height(self) -> int:
        return len(self.blocks) - 1

    @property
    def tip(self) -> dict:
        return self.blocks[-1]

    def headers(self, lo: int = 0, hi: int | None = None) -> list[dict]:
        hi = self.height if hi is None else min(hi, self.height)
        return [header_of(b) for b in self.blocks[max(0, lo):hi + 1]]

    def emission(self, height: int) -> int:
        """Block subsidy at a height before the pool cap is applied."""
        return params.INITIAL_BLOCK_REWARD >> (height // self.profile["halving_interval"])

    def subsidy(self, height: int, state: State | None = None) -> int:
        st = state or self.state
        return min(self.emission(height), st.mining_pool_remaining)

    def _target_at(self, headers: list[dict], height: int) -> int:
        """Target for the block at `height`, given the headers before it."""
        if height <= 0:
            return self.profile["max_target"]
        window = self.profile["difficulty_window"]
        prev = headers[height - 1]
        prev_target = B.hex_to_target(prev["target"])
        if height % window != 0 or height < window:
            return prev_target
        first = headers[height - window]
        actual = max(1, prev["timestamp"] - first["timestamp"])
        expected = window * self.profile["target_block_time"]
        actual = max(expected // 4, min(expected * 4, actual))       # clamp swing to 4x
        return max(1, min(self.profile["max_target"], prev_target * actual // expected))

    def target_for_height(self, height: int) -> int:
        return self._target_at(self.blocks, height)

    @staticmethod
    def work_of(headers: list[dict]) -> int:
        return sum(B.work_for_target(B.hex_to_target(h["target"])) for h in headers[1:])

    def cumulative_work(self) -> int:
        return self.work_of(self.blocks)

    def get_tx(self, txid: str) -> dict | None:
        loc = self.tx_index.get(txid)
        if loc:
            h, i = loc
            return {"tx": self.blocks[h]["txs"][i], "height": h, "index": i, "status": "confirmed"}
        if txid in self.mempool:
            return {"tx": self.mempool[txid], "height": None, "index": None, "status": "pending"}
        return None

    def get_ciphertext(self, packet_id: str) -> str | None:
        """Inline ciphertext of a confirmed listing, read from its block."""
        loc = self.tx_index.get(packet_id)
        if not loc:
            return None
        h, i = loc
        tx = self.blocks[h]["txs"][i]
        return tx.get("payload", {}).get("ciphertext") if tx.get("type") == T.LIST_PACKET else None

    def supply(self) -> dict:
        st = self.state
        protocol_held = st.balance(params.TREASURY_ADDRESS) + st.balance(params.FOUNDING_POOL_ADDRESS)
        return {
            "max_supply": params.MAX_SUPPLY,
            "circulating": sum(st.balances.values()) + st.escrow_locked - protocol_held,
            "treasury_unallocated": st.balance(params.TREASURY_ADDRESS),
            "founding_pool_remaining": st.balance(params.FOUNDING_POOL_ADDRESS),
            "mining_pool_remaining": st.mining_pool_remaining,
            "mined_so_far": st.minted,
            "escrow_locked": st.escrow_locked,
            "grants_issued": len(st.grants),
            "founding_slots_taken": len(st.founders),
            "registered_llms": len(st.llms),
        }

    # ------------------------------------------------------- validation
    @staticmethod
    def _median_time_past(headers: list[dict], upto_height: int) -> int:
        ts = sorted(b["timestamp"] for b in headers[max(0, upto_height - 11):upto_height])
        return ts[len(ts) // 2] if ts else 0

    def check_header(self, hdr: dict, prev_headers: list[dict], now: int | None = None, upto: int | None = None) -> None:
        """Cheap checks: shape, linking, timestamp, target schedule, hash, PoW.
        `upto` treats only prev_headers[:upto] as the chain being extended, so
        a long header list can be validated without slicing it per block."""
        now = int(time.time()) if now is None else now
        n = len(prev_headers) if upto is None else upto
        if not isinstance(hdr, dict):
            raise BlockError("block must be an object")
        for k in HEADER_FIELDS:
            if k not in hdr:
                raise BlockError(f"block missing {k}")
        h = hdr["height"]
        if not isinstance(h, int) or h != n:
            raise BlockError(f"block height {h} does not extend height {n - 1}")
        if hdr["prev_hash"] != prev_headers[n - 1]["hash"]:
            raise BlockError("prev_hash does not match tip")
        if not isinstance(hdr["timestamp"], int) or not isinstance(hdr["nonce"], int):
            raise BlockError("timestamp and nonce must be ints")
        if hdr["timestamp"] <= self._median_time_past(prev_headers, h):
            raise BlockError("timestamp not after median of previous blocks")
        if hdr["timestamp"] > now + params.MAX_FUTURE_DRIFT:
            raise BlockError("timestamp too far in the future")
        if not isinstance(hdr["target"], str) or len(hdr["target"]) != 64:
            raise BlockError("malformed target")
        try:
            if B.hex_to_target(hdr["target"]) != self._target_at(prev_headers, h):
                raise BlockError("wrong difficulty target")
        except ValueError:
            raise BlockError("malformed target")
        if not isinstance(hdr["hash"], str) or B.block_hash(hdr) != hdr["hash"]:
            raise BlockError("hash does not match header")
        if not B.pow_ok(hdr):
            raise BlockError("proof of work not satisfied")

    def check_headers(self, headers: list[dict], now: int | None = None) -> int:
        """Validate a full header chain from genesis. Returns its cumulative work."""
        if not headers or headers[0]["hash"] != self.blocks[0]["hash"]:
            raise BlockError("candidate chain has a different genesis")
        for i in range(1, len(headers)):
            self.check_header(headers[i], headers, now, upto=i)
        return self.work_of(headers)

    def _check_body(self, blk: dict) -> list[str]:
        txs = blk.get("txs")
        if not isinstance(txs, list) or not txs:
            raise BlockError("block needs at least a coinbase")
        if len(txs) > params.MAX_BLOCK_TXS + 1:
            raise BlockError("too many transactions")
        if not all(isinstance(t, dict) for t in txs):
            raise BlockError("transactions must be objects")
        if len(canonical_json(txs)) > params.MAX_BLOCK_BYTES:
            raise BlockError("block too large")
        ids = [T.txid(t) for t in txs]
        if len(set(ids)) != len(ids):
            raise BlockError("duplicate transaction in block")
        if blk["merkle_root"] != B.merkle_root(ids):
            raise BlockError("merkle root mismatch")
        for i in ids:
            if i in self.tx_index:
                raise BlockError(f"transaction {i[:12]} already confirmed")
        return ids

    def add_block(self, blk: dict, now: int | None = None) -> None:
        """Validate against the tip and apply. On failure nothing changes."""
        with self.lock:
            self.check_header(blk, self.blocks, now)
            ids = self._check_body(blk)
            h = blk["height"]
            st = self.state
            st.begin()
            try:
                fees = 0
                for t in blk["txs"][1:]:
                    if t.get("type") in T.SYSTEM_TYPES:
                        raise BlockError("system transaction in body")
                    try:
                        fees += st.apply_tx(t, h)
                    except TxError as e:
                        raise BlockError(f"invalid tx {T.txid(t)[:12]}: {e}")
                try:
                    st.apply_coinbase(blk["txs"][0], h, self.subsidy(h, st), fees)
                except TxError as e:
                    raise BlockError(f"invalid coinbase: {e}")
                st.check_invariant()
            except Exception:
                st.rollback()
                raise
            st.commit()
            self.blocks.append(blk)
            for i, tid in enumerate(ids):
                self.tx_index[tid] = (h, i)
            self._rebuild_mempool()

    # ------------------------------------------------------------ mempool
    def add_tx(self, tx: dict) -> str:
        with self.lock:
            if not isinstance(tx, dict):
                raise TxError("transaction must be an object")
            tid = T.txid(tx)
            if tid in self.mempool or tid in self.tx_index:
                return tid
            if len(self.mempool) >= params.MAX_MEMPOOL_TXS:
                raise TxError("mempool full, try again later")
            sender = tx.get("from")
            if sum(1 for t in self.mempool.values() if t["from"] == sender) >= params.MAX_PENDING_PER_SENDER:
                raise TxError("too many pending transactions from this sender")
            self._mempool_state.apply_tx(tx, self.height + 1)   # raises TxError, leaves state untouched
            self.mempool[tid] = tx
            return tid

    def _rebuild_mempool(self) -> None:
        old = list(self.mempool.values())
        self.mempool = {}
        self._mempool_state = self.state.copy()
        for tx in old:
            if T.txid(tx) in self.tx_index:
                continue
            try:
                self.add_tx(tx)
            except TxError:
                pass

    # ------------------------------------------------------------- mining
    def block_template(self, miner: str, timestamp: int | None = None) -> dict:
        with self.lock:
            h = self.height + 1
            ts = int(time.time()) if timestamp is None else timestamp
            ts = max(ts, self._median_time_past(self.blocks, h) + 1)
            st = self.state
            st.begin()
            chosen, fees, size = [], 0, 2
            try:
                for tx in self.mempool.values():
                    if len(chosen) >= params.MAX_BLOCK_TXS:
                        break
                    tx_bytes = T.tx_size(tx) + 1
                    if size + tx_bytes > params.MAX_BLOCK_BYTES - 1024:
                        continue
                    try:
                        fees += st.apply_tx(tx, h)
                        chosen.append(tx)
                        size += tx_bytes
                    except TxError:
                        continue
                cb = T.coinbase(h, miner, self.subsidy(h, st) + fees, self.profile["chain_id"])
            finally:
                st.rollback()
            return B.make_block(h, self.tip["hash"], ts, self.target_for_height(h), [cb] + chosen)

    def mine_block(self, miner: str, max_iters: int | None = None, should_stop=None, timestamp: int | None = None) -> dict | None:
        blk = self.block_template(miner, timestamp)
        if not B.mine(blk, max_iters, should_stop):
            return None
        self.add_block(blk)
        return blk

    # --------------------------------------------------------- fork choice
    def replace_with(self, blocks: list[dict], now: int | None = None) -> bool:
        """Adopt `blocks` (a full chain from genesis) if it carries more work.
        Headers are verified before any transaction is replayed."""
        with self.lock:
            if self.check_headers(blocks, now) <= self.cumulative_work():
                return False
            candidate = Chain(self.genesis)
            for b in blocks[1:]:
                candidate.add_block(b, now)
            old_mempool = list(self.mempool.values())
            self.blocks, self.state, self.tx_index = candidate.blocks, candidate.state, candidate.tx_index
            self.mempool = {}
            self._mempool_state = self.state.copy()
            for tx in old_mempool:
                try:
                    self.add_tx(tx)
                except TxError:
                    pass
            return True

    # --------------------------------------------------------- persistence
    def save(self, path: str) -> None:
        with self.lock:
            tmp = path + ".tmp"
            with open(tmp, "w") as f:
                json.dump({"genesis": self.genesis, "blocks": self.blocks}, f)
            os.replace(tmp, path)

    @classmethod
    def load(cls, path: str) -> "Chain":
        with open(path) as f:
            d = json.load(f)
        chain = cls(d["genesis"])
        for b in d["blocks"][1:]:
            chain.add_block(b, now=b["timestamp"] + params.MAX_FUTURE_DRIFT)
        return chain

    @classmethod
    def from_genesis_file(cls, path: str) -> "Chain":
        with open(path) as f:
            return cls(json.load(f))
