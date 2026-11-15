"""
The chain: block validation, mempool, mining, fork choice and persistence.

Validation is two-phase. Header checks (linking, hash, proof-of-work, target
schedule) are cheap and run first, on any candidate chain, before a single
transaction is replayed. Only a candidate whose headers already carry more
work than ours gets its transactions applied.

A node keeps the headers in memory and the block bodies in an append-only
file, one block per line (blocks.jsonl). Every hundred blocks the state is
written next to it, so a restart replays the last couple of hundred blocks
rather than the chain from genesis. Each of the last MAX_REORG_DEPTH blocks
leaves an undo record: a fork within the reorg limit is taken by rolling
those blocks back and applying the other branch, not by rebuilding the chain.
None of this changes what a valid block or a valid chain is.
"""

from __future__ import annotations

import collections
import hashlib
import json
import os
import random
import re
import sys
import threading
import time

from . import block as B, params, tx as T
from .crypto import canonical_json
from .state import State, TxError

HEADER_FIELDS = ("height", "prev_hash", "timestamp", "target", "merkle_root", "nonce", "hash")

BLOCKS_FILE = "blocks.jsonl"     # the block file in a node's data directory
SNAPSHOT_EVERY = 100             # blocks between two state snapshots
SNAPSHOTS_KEPT = 3               # so one is always at least MAX_REORG_DEPTH blocks behind the tip
BODY_CACHE = 256                 # block bodies kept in memory by a disk store


class BlockError(Exception):
    pass


class ReorgTooDeep(BlockError):
    """A heavier chain was offered that would undo more than MAX_REORG_DEPTH blocks."""


class WrongGenesis(Exception):
    """The block file in the data directory belongs to another chain. `found` is its genesis hash."""

    def __init__(self, found: str):
        super().__init__(f"block file starts with genesis {found[:8]}...")
        self.found = found


def header_of(block: dict) -> dict:
    return {k: block[k] for k in HEADER_FIELDS}


def _work(headers: list[dict]) -> int:
    return sum(B.work_for_target(B.hex_to_target(h["target"])) for h in headers)


class MemoryBlocks:
    """Block bodies in a list: tests, tools, light use."""

    def __init__(self):
        self._b: list[dict] = []

    def __len__(self) -> int:
        return len(self._b)

    def append(self, blk: dict) -> None:
        self._b.append(blk)

    def get(self, h: int) -> dict:
        if h < 0:
            raise IndexError("no such block")
        return self._b[h]

    def slice(self, lo: int, hi: int) -> list[dict]:
        return self._b[max(0, lo):max(0, hi)]

    def truncate(self, n: int) -> None:
        del self._b[n:]

    def sync(self) -> None:
        pass


class DiskBlocks:
    """Block bodies in an append-only file, one JSON block per line. Memory holds where each line starts and
    the most recently used blocks. The file is opened per operation and never held open."""

    def __init__(self, path: str):
        self.path = path
        self._off = [0]                  # _off[h] is where block h starts; the last entry is the end of the file
        self._cache: collections.OrderedDict[int, dict] = collections.OrderedDict()
        self._dirty = False              # written since the last fsync
        self._lock = threading.Lock()

    def __len__(self) -> int:
        return len(self._off) - 1

    def load(self, accept) -> int:
        """Index the file, handing each block to accept(height, block) in order. The file ends at the first
        line that is torn (a crash mid-write), is not JSON, or that `accept` refuses with a BlockError: what
        follows is cut off. Returns the number of bytes cut."""
        if not os.path.exists(self.path):
            return 0
        offs, good = [0], 0
        with open(self.path, "rb") as f:
            for line in f:
                if not line.endswith(b"\n"):
                    break
                try:
                    accept(len(offs) - 1, json.loads(line))
                except (ValueError, KeyError, TypeError, BlockError):
                    break
                good += len(line)
                offs.append(good)
            size = f.seek(0, os.SEEK_END)
        self._off = offs
        if size > good:
            if good == 0:                # not even a first block: keep the file for a look, start a new one
                os.replace(self.path, self.path + ".unreadable")
            else:
                with open(self.path, "r+b") as f:
                    f.truncate(good)
                    f.flush()
                    os.fsync(f.fileno())
        return size - good

    def _remember(self, h: int, blk: dict) -> None:
        self._cache[h] = blk
        self._cache.move_to_end(h)
        while len(self._cache) > BODY_CACHE:
            self._cache.popitem(last=False)

    def append(self, blk: dict) -> None:
        line = canonical_json(blk) + b"\n"
        with self._lock:
            end = self._off[-1]
            exists = os.path.exists(self.path)
            if end and not exists:
                raise OSError(f"{self.path} is gone")
            with open(self.path, "r+b" if exists else "wb") as f:
                f.seek(end)
                f.write(line)
                f.truncate()
                f.flush()                # with the operating system now; on the disk at the next sync()
            self._off.append(end + len(line))
            self._remember(len(self._off) - 2, blk)
            self._dirty = True

    def get(self, h: int) -> dict:
        with self._lock:
            if not 0 <= h < len(self._off) - 1:
                raise IndexError("no such block")
            blk = self._cache.get(h)
            if blk is None:
                with open(self.path, "rb") as f:
                    f.seek(self._off[h])
                    blk = json.loads(f.read(self._off[h + 1] - self._off[h]))
            self._remember(h, blk)
            return blk

    def slice(self, lo: int, hi: int) -> list[dict]:
        """Blocks lo..hi-1, read in one go."""
        with self._lock:
            lo, hi = max(0, lo), min(hi, len(self._off) - 1)
            if hi <= lo:
                return []
            if hi - lo == 1 and lo in self._cache:
                return [self._cache[lo]]
            with open(self.path, "rb") as f:
                f.seek(self._off[lo])
                raw = f.read(self._off[hi] - self._off[lo])
        return [json.loads(line) for line in raw.split(b"\n")[:-1]]

    def truncate(self, n: int) -> None:
        """Keep the first n blocks."""
        with self._lock:
            if n >= len(self._off) - 1:
                return
            del self._off[n + 1:]
            for h in [h for h in self._cache if h >= n]:
                del self._cache[h]
            with open(self.path, "r+b") as f:
                f.truncate(self._off[-1])
            self._dirty = True

    def sync(self) -> None:
        with self._lock:
            if self._dirty and os.path.exists(self.path):
                with open(self.path, "r+b") as f:
                    os.fsync(f.fileno())
            self._dirty = False


class _Blocks:
    """`chain.blocks`: the blocks as a read-only sequence (index, slice, iterate), wherever they are stored."""

    def __init__(self, chain: "Chain"):
        self._c = chain

    def __len__(self) -> int:
        return len(self._c.hdrs)

    def __getitem__(self, i):
        n = len(self)
        if isinstance(i, slice):
            lo, hi, step = i.indices(n)
            if step == 1:
                return self._c.store.slice(lo, hi)
            return [self._c.store.get(j) for j in range(lo, hi, step)]
        if i < 0:
            i += n
        if not 0 <= i < n:
            raise IndexError("no such block")
        return self._c.store.get(i)

    def __iter__(self):
        for lo in range(0, len(self), 500):
            yield from self._c.store.slice(lo, min(lo + 500, len(self)))

    def __reversed__(self):
        for i in range(len(self) - 1, -1, -1):
            yield self._c.store.get(i)


class Chain:
    def __init__(self, genesis: dict, store=None):
        """`store` holds the block bodies: in memory when left out, else a DiskBlocks (see Chain.open)."""
        self.genesis = genesis
        profile_name = genesis.get("profile", "mainnet")
        if profile_name not in params.PROFILES:
            raise BlockError(f"unknown profile {profile_name}")
        self.profile = dict(params.PROFILES[profile_name])
        self.profile_name = profile_name
        self.store = MemoryBlocks() if store is None else store
        self._slim = store is not None   # headers kept apart from the bodies, which live on disk
        self.hdrs: list[dict] = []       # every header, by height (in memory mode: the blocks themselves)
        self.data_dir: str | None = None
        self.state = State(self.profile)
        self.mempool: dict[str, dict] = {}
        self._mp_state: State | None = None
        self.tx_index: dict[str, tuple[int, int]] = {}
        self._total_work = 0
        self._undo: collections.deque = collections.deque(maxlen=params.MAX_REORG_DEPTH)   # journals of the newest blocks
        self._snap_height = 0            # height of the newest state snapshot on disk
        self._snap_lock = threading.Lock()
        self.refused_reorgs = 0          # heavier forks turned away by the reorg limit
        self.lock = threading.RLock()
        self._apply_genesis_block(fresh=store is None)

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

    def _genesis_state(self) -> State:
        st = State(self.profile)
        p = self._genesis_block()["txs"][0]["payload"]
        st.apply_genesis(p["allocations"], p["registrars"], p["registrar_threshold"])
        return st

    def _apply_genesis_block(self, fresh: bool = True) -> None:
        """`fresh` puts the genesis block in the store; a store opened from disk already has it (or gets it
        from Chain.open)."""
        blk = self._genesis_block()
        self.state = self._genesis_state()
        if fresh:
            self.store.append(blk)
        self.hdrs.append(self._hdr(blk))
        self.tx_index[T.txid(blk["txs"][0])] = (0, 0)

    def _hdr(self, blk: dict) -> dict:
        """What `hdrs` keeps of a block: the block itself in memory mode, a compact header otherwise."""
        if not self._slim:
            return blk
        h = header_of(blk)
        h["target"] = sys.intern(h["target"])
        if self.hdrs and h["prev_hash"] == self.hdrs[-1]["hash"]:
            h["prev_hash"] = self.hdrs[-1]["hash"]       # one string, not two copies of it
        return h

    # ------------------------------------------------------------ queries
    @property
    def height(self) -> int:
        return len(self.hdrs) - 1

    @property
    def blocks(self) -> _Blocks:
        return _Blocks(self)

    @property
    def tip(self) -> dict:
        return self.store.get(self.height)

    def headers(self, lo: int = 0, hi: int | None = None) -> list[dict]:
        hi = self.height if hi is None else min(hi, self.height)
        return [header_of(b) for b in self.hdrs[max(0, lo):hi + 1]]

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
        return self._target_at(self.hdrs, height)

    @staticmethod
    def work_of(headers: list[dict]) -> int:
        return _work(headers[1:])

    def cumulative_work(self) -> int:
        return self._total_work

    def _confirmed_tx(self, txid: str) -> tuple[dict, int, int] | None:
        loc = self.tx_index.get(txid)
        if not loc:
            return None
        h, i = loc
        try:
            tx = self.store.get(h)["txs"][i]
        except IndexError:               # its block was undone by a reorg between the two reads
            return None
        return (tx, h, i) if T.txid(tx) == txid else None

    def get_tx(self, txid: str) -> dict | None:
        found = self._confirmed_tx(txid)
        if found:
            return {"tx": found[0], "height": found[1], "index": found[2], "status": "confirmed"}
        tx = self.mempool.get(txid)
        if tx is not None:
            return {"tx": tx, "height": None, "index": None, "status": "pending"}
        return None

    def get_ciphertext(self, packet_id: str) -> str | None:
        """Inline ciphertext of a confirmed listing or letter, read from its block."""
        found = self._confirmed_tx(packet_id)
        if not found:
            return None
        tx = found[0]
        return tx.get("payload", {}).get("ciphertext") if tx.get("type") in (T.LIST_PACKET, T.SEND_LETTER) else None

    def pending_txs(self) -> list[dict]:
        """The mempool as a list. Safe without the chain lock: the mempool is only ever added to or swapped whole."""
        return list(self.mempool.values())

    def supply(self) -> dict:
        st = self.state
        protocol_held = st.balance(params.TREASURY_ADDRESS) + st.balance(params.FOUNDING_POOL_ADDRESS)
        return {
            "max_supply": params.MAX_SUPPLY,
            "circulating": sum(st.balances.values()) + st.escrow_locked - protocol_held,
            "treasury_unallocated": st.balance(params.TREASURY_ADDRESS),
            "founding_pool_remaining": st.balance(params.FOUNDING_POOL_ADDRESS),
            "reserve": st.balance(params.RESERVE_ADDRESS),
            "mining_pool_remaining": st.mining_pool_remaining,
            "mined_so_far": st.minted,
            "escrow_locked": st.escrow_locked,
            "grants_issued": len(st.grants),
            "founding_slots_taken": len(st.founders),
            "registered_llms": len(st.llms),
            "accounts": len(st.llms),
            "people": sum(1 for r in st.llms.values() if r.get("kind") == "person"),
            "letters": len(st.letters),
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
        if not headers or headers[0]["hash"] != self.hdrs[0]["hash"]:
            raise BlockError("candidate chain has a different genesis")
        for i in range(1, len(headers)):
            self.check_header(headers[i], headers, now, upto=i)
        return self.work_of(headers)

    def check_extension(self, common: int, headers: list[dict], now: int | None = None) -> int:
        """Validate `headers` as a branch that leaves our chain after block `common`. Returns the cumulative
        work of our chain up to `common` plus that branch. Only the new headers are checked: ours already were."""
        with self.lock:
            if not isinstance(common, int) or not 0 <= common <= self.height:
                raise BlockError("no such fork point")
            full = self.hdrs[:common + 1] + list(headers)
            base = self._total_work - _work(self.hdrs[common + 1:])
        for i in range(common + 1, len(full)):
            self.check_header(full[i], full, now, upto=i)
        return base + _work(full[common + 1:])

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

    def _apply_state(self, blk: dict, st: State | None = None) -> list:
        """Apply a block's transactions to the state (ours unless one is given). Returns the journal that
        undoes them (State.undo). On failure the state is left as it was."""
        st = self.state if st is None else st
        h = blk["height"]
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
        return st.detach()

    def _index(self, blk: dict, ids: list[str]) -> None:
        """Record a block that now follows our tip: header, where its transactions are, its work."""
        h = blk["height"]
        self.hdrs.append(self._hdr(blk))
        for i, tid in enumerate(ids):
            self.tx_index[tid] = (h, i)
        self._total_work += B.work_for_target(B.hex_to_target(blk["target"]))

    def _append_block(self, blk: dict, now: int | None = None) -> None:
        """Validate against the tip, apply, store. On failure nothing changes. The mempool is not touched."""
        self.check_header(blk, self.hdrs, now)
        ids = self._check_body(blk)
        journal = self._apply_state(blk)
        try:
            self.store.append(blk)
        except OSError as e:
            self.state.undo(journal)
            raise BlockError(f"could not store block {blk['height']}: {e}")
        self._index(blk, ids)
        self._undo.append(journal)

    def add_block(self, blk: dict, now: int | None = None) -> None:
        """Validate against the tip and apply. On failure nothing changes."""
        with self.lock:
            self._append_block(blk, now)
            self._rebuild_mempool()

    # ------------------------------------------------------------ mempool
    @property
    def _mempool_state(self) -> State:
        """The state with the mempool applied: what the next transaction is checked against. Copied from the
        chain state when first needed after a block, not on every block (most blocks meet an empty mempool)."""
        if self._mp_state is None:
            self._mp_state = self.state.copy()
        return self._mp_state

    @_mempool_state.setter
    def _mempool_state(self, st: State | None) -> None:
        self._mp_state = st

    def add_tx(self, tx: dict) -> str:
        with self.lock:
            return self._admit(tx, self.mempool)

    def _admit(self, tx: dict, pool: dict[str, dict]) -> str:
        if not isinstance(tx, dict):
            raise TxError("transaction must be an object")
        tid = T.txid(tx)
        if tid in pool or tid in self.tx_index:
            return tid
        if len(pool) >= params.MAX_MEMPOOL_TXS:
            raise TxError("mempool full, try again later")
        sender = tx.get("from")
        if sum(1 for t in pool.values() if t["from"] == sender) >= params.MAX_PENDING_PER_SENDER:
            raise TxError("too many pending transactions from this sender")
        self._mempool_state.apply_tx(tx, self.height + 1)   # raises TxError, leaves state untouched
        pool[tid] = tx
        return tid

    def _rebuild_mempool(self, first: list[dict] | None = None) -> None:
        """Check what is waiting against the new tip. `first` (transactions of blocks a reorg undid) goes in
        ahead of the rest. The new mempool is swapped in whole, so a reader without the lock never sees it
        half-built."""
        waiting = list(first or []) + list(self.mempool.values())
        pool: dict[str, dict] = {}
        self._mp_state = None
        for tx in waiting:
            if T.txid(tx) in self.tx_index:
                continue
            try:
                self._admit(tx, pool)
            except TxError:
                pass
        self.mempool = pool

    # ------------------------------------------------------------- mining
    def block_template(self, miner: str, timestamp: int | None = None) -> dict:
        with self.lock:
            h = self.height + 1
            ts = int(time.time()) if timestamp is None else timestamp
            ts = max(ts, self._median_time_past(self.hdrs, h) + 1)
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
            # Start the nonce search at a random point. A miner whose clock is
            # behind the chain gets the same minimum timestamp on every
            # template; starting from 0 each time would retry the same nonces.
            return B.make_block(h, self.hdrs[-1]["hash"], ts, self.target_for_height(h), [cb] + chosen,
                                nonce=random.getrandbits(48))

    def mine_block(self, miner: str, max_iters: int | None = None, should_stop=None, timestamp: int | None = None) -> dict | None:
        blk = self.block_template(miner, timestamp)
        if not B.mine(blk, max_iters, should_stop):
            return None
        self.add_block(blk)
        return blk

    # --------------------------------------------------------- fork choice
    def fork_point(self, headers: list[dict]) -> int:
        """Height of the last block we share with a candidate chain."""
        n = min(len(headers), len(self.hdrs))
        common = 0
        for i in range(n):
            if headers[i]["hash"] != self.hdrs[i]["hash"]:
                break
            common = i
        return common

    def reorg_allowed(self, headers: list[dict], max_depth: int = params.MAX_REORG_DEPTH) -> bool:
        """Rolling finality: a reorg may undo at most `max_depth` of our blocks."""
        return self.height - self.fork_point(headers) <= max_depth

    def _drop_above(self, common: int, removed: list[dict]) -> None:
        """Forget the blocks above `common` (their effect on the state is already undone)."""
        for blk in removed:
            for t in blk["txs"]:
                self.tx_index.pop(T.txid(t), None)
        self._total_work -= _work(self.hdrs[common + 1:])
        del self.hdrs[common + 1:]
        self.store.truncate(common + 1)

    def _replay(self, st: State, lo: int, hi: int, undo=None) -> tuple[int, Exception] | None:
        """Apply stored blocks lo..hi to `st`, collecting their journals in `undo` when given. Returns
        (height, error) for the first block that does not apply; `st` is then at the block before it."""
        for a in range(lo, hi + 1, 500):
            for blk in self.store.slice(a, min(a + 500, hi + 1)):
                try:
                    journal = self._apply_state(blk, st)
                except Exception as e:  # noqa: BLE001  whatever it is, this block does not apply
                    return blk["height"], e
                if undo is not None:
                    undo.append(journal)
        return None

    def _rollback_to(self, common: int) -> list[dict]:
        """Undo our blocks above `common`. Returns them, oldest first."""
        removed = self.store.slice(common + 1, self.height + 1)
        if len(removed) <= len(self._undo):
            for _ in removed:
                self.state.undo(self._undo.pop())
        else:
            # no undo records that far back (a restart from a recent snapshot): rebuild the state at `common`
            st, h = self._base_state(common)
            failed = self._replay(st, h + 1, common)
            if failed is not None:
                raise BlockError(f"cannot rebuild the state at block {common}: block {failed[0]}: {failed[1]}")
            self.state = st
            self._undo.clear()
        self._drop_above(common, removed)
        return removed

    def reorg_from(self, common: int, new_blocks: list[dict], now: int | None = None) -> bool:
        """Adopt the branch `new_blocks` that leaves our chain after block `common`, if it carries more work than
        ours and does not undo more than MAX_REORG_DEPTH of our own blocks. Headers are verified before any
        transaction is replayed. Our blocks above `common` are rolled back with their undo records and the new
        ones applied; if one of those turns out invalid, ours are put back and nothing has changed."""
        with self.lock:
            new_blocks = list(new_blocks)
            if self.check_extension(common, new_blocks, now) <= self._total_work:
                return False
            depth = self.height - common
            if depth > params.MAX_REORG_DEPTH:
                self.refused_reorgs += 1
                raise ReorgTooDeep(f"candidate chain forks {depth} blocks back, limit is {params.MAX_REORG_DEPTH}")
            removed = self._rollback_to(common)
            try:
                for b in new_blocks:
                    self._append_block(b, now)
            except Exception:
                self._rollback_to(common)
                for b in removed:
                    self._append_block(b, now=b["timestamp"])
                raise
            self._drop_snapshots_above(common)
            # what our undone blocks carried goes back to the mempool, ahead of what was already waiting
            self._rebuild_mempool([t for b in removed for t in b["txs"][1:]])
            return True

    def replace_with(self, blocks: list[dict], now: int | None = None) -> bool:
        """Adopt `blocks` (a full chain from genesis) if it carries more work
        and does not undo more than MAX_REORG_DEPTH of our own blocks.
        Headers are verified before any transaction is replayed."""
        with self.lock:
            if not blocks or blocks[0]["hash"] != self.hdrs[0]["hash"]:
                raise BlockError("candidate chain has a different genesis")
            common = self.fork_point(blocks)
            return self.reorg_from(common, blocks[common + 1:], now)

    # --------------------------------------------------------- persistence
    def save(self, path: str) -> None:
        """The whole chain as one JSON file: how a node stored it before 0.10.2, still handy for tools and tests."""
        with self.lock:
            tmp = path + ".tmp"
            with open(tmp, "w") as f:
                json.dump({"genesis": self.genesis, "blocks": self.store.slice(0, len(self.hdrs))}, f)
                f.flush()
                os.fsync(f.fileno())          # the rename must not outlive the data on a crash
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
    def open(cls, genesis: dict, data_dir: str, log=None) -> "Chain":
        """The chain kept in `data_dir`: block file indexed and checked (headers, proof-of-work, merkle roots),
        state restored from a snapshot plus the blocks since. A file that ends in a torn or invalid block is cut
        there and the node resyncs the rest from its peers. Raises WrongGenesis when the file is another chain's."""
        log = log or (lambda msg: None)
        os.makedirs(data_dir, exist_ok=True)
        chain = cls(genesis, store=DiskBlocks(os.path.join(data_dir, BLOCKS_FILE)))
        chain.data_dir = data_dir

        def accept(n: int, blk: dict) -> None:
            if n == 0:
                found = blk.get("hash") if isinstance(blk, dict) else None
                if found != chain.hdrs[0]["hash"]:
                    raise WrongGenesis(str(found))
                return
            chain.check_header(blk, chain.hdrs, now=blk["timestamp"])
            chain._index(blk, chain._check_body(blk))

        cut = chain.store.load(accept)
        if len(chain.store) == 0:
            chain.store.append(chain._genesis_block())
        if cut:
            log(f"block file ended in {cut} bytes that are not a valid next block; cut back to block {chain.height}")
        chain._restore_state(log)
        return chain

    def _restore_state(self, log) -> None:
        """Bring the state to the stored tip. Starts from the newest snapshot at least MAX_REORG_DEPTH blocks
        back when there is one, so the replay also rebuilds the undo records a reorg may ask for; otherwise from
        the oldest snapshot there is, otherwise from genesis (always, with BERRY_FULL_REPLAY set)."""
        tip = self.height
        snaps = [] if os.environ.get("BERRY_FULL_REPLAY") else [s for s in self._snapshots() if s[0] <= tip]
        deep = [s for s in snaps if s[0] <= tip - params.MAX_REORG_DEPTH]
        order = deep[::-1] + [s for s in snaps if s not in deep] + [(0, None)]
        for start, path in order:
            st = self._genesis_state() if path is None else self._read_snapshot(start, path)
            if st is None:
                continue
            self._undo.clear()
            failed = self._replay(st, start + 1, tip, self._undo)
            if failed is None or path is None:
                break
            log(f"state snapshot at block {start} does not lead to the stored tip (block {failed[0]}: {failed[1]}); "
                f"trying another start")
        self.state = st
        if failed is not None:
            log(f"stored block {failed[0]} does not apply ({failed[1]}); keeping the chain up to block {failed[0] - 1}")
            self._drop_above(failed[0] - 1, self.store.slice(failed[0], tip + 1))
        self._drop_snapshots_above(self.height)
        self._snap_height = max((s[0] for s in self._snapshots()), default=0)
        if tip:
            log(f"chain at block {self.height}: state from {'block ' + str(start) if path else 'genesis'}, "
                f"{self.height - start} blocks replayed")

    def _snapshots(self) -> list[tuple[int, str]]:
        """(height, path) of every state snapshot in the data directory, oldest first."""
        out = []
        if self.data_dir:
            for name in os.listdir(self.data_dir):
                m = re.fullmatch(r"state-(\d+)\.json", name)
                if m:
                    out.append((int(m.group(1)), os.path.join(self.data_dir, name)))
        return sorted(out)

    def _read_snapshot(self, height: int, path: str) -> State | None:
        """The state a snapshot holds, if it is whole (its hash matches) and was taken on our chain."""
        try:
            with open(path, "rb") as f:
                meta = json.loads(f.readline())
                body = f.readline().rstrip(b"\n")
            if meta["height"] != height or meta["hash"] != self.hdrs[height]["hash"]:
                return None
            if hashlib.sha256(body).hexdigest() != meta["state_root"]:
                return None
            return State.from_dict(json.loads(body), self.profile)
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            return None

    def _base_state(self, upto: int) -> tuple[State, int]:
        """The newest snapshot at or below block `upto` that checks out, else the genesis state."""
        for h, path in reversed(self._snapshots()):
            if h <= upto:
                st = self._read_snapshot(h, path)
                if st is not None:
                    return st, h
        return self._genesis_state(), 0

    def _drop_snapshots_above(self, height: int) -> None:
        for h, path in self._snapshots():
            if h > height:
                try:
                    os.remove(path)
                except OSError:
                    pass
        self._snap_height = min(self._snap_height, height)

    def persist(self) -> None:
        """Make the chain durable: the block file is flushed to disk and, every SNAPSHOT_EVERY blocks, the state
        is written out so the next start need not replay from genesis. Nothing to do without a data directory."""
        if self.data_dir is None:
            return
        self.store.sync()
        snap = None
        with self.lock:
            h = self.height
            if h - self._snap_height >= SNAPSHOT_EVERY:
                snap = (h, self.hdrs[h]["hash"], canonical_json(self.state.to_dict()))
                self._snap_height = h
        if snap:                              # written outside the chain lock: nobody waits on the disk
            self._write_snapshot(*snap)

    def _write_snapshot(self, height: int, block_hash: str, body: bytes) -> None:
        meta = {"format": 1, "height": height, "hash": block_hash, "state_root": hashlib.sha256(body).hexdigest()}
        path = os.path.join(self.data_dir, f"state-{height}.json")
        with self._snap_lock:
            with open(path + ".tmp", "wb") as f:
                f.write(json.dumps(meta).encode() + b"\n" + body + b"\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(path + ".tmp", path)
            for _, old in self._snapshots()[:-SNAPSHOTS_KEPT]:
                try:
                    os.remove(old)
                except OSError:
                    pass

    @classmethod
    def from_genesis_file(cls, path: str) -> "Chain":
        with open(path) as f:
            return cls(json.load(f))
