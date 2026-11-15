"""How a node keeps its chain: the block file and state snapshots in the data
directory, undo records for short reorgs, and the takeover of a chain.json
left by a version before 0.10.2. None of it may change what the chain is:
every path here must end at the same state root as a replay from genesis."""

import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from berrychain import block as Bk, chain as chain_mod, params, tx as T  # noqa: E402
from berrychain.chain import BLOCKS_FILE, BlockError, Chain  # noqa: E402
from berrychain.crypto import canonical_json  # noqa: E402
from berrychain.node import Node, make_handler, open_or_create  # noqa: E402
from berrychain.state import State  # noqa: E402
from berrychain.wallet import Wallet  # noqa: E402
from test_chain import Harness  # noqa: E402
from test_node import FakePeerTransport, mine_alone  # noqa: E402

B = params.berry
LATER = params.MAX_FUTURE_DRIFT


def busy_harness() -> Harness:
    """A chain that has seen registrations, founding grants, transfers and a letter."""
    h = Harness(founders=3)
    a, b = h.founders[0], h.founders[1]
    h.send(a, T.TRANSFER, {"to": b.address, "amount": B(5)})
    h.mine()
    h.fund_and_register("late")
    h.send(b, T.TRANSFER, {"to": a.address, "amount": B(2)})
    h.mine(2)
    return h


def copy_into(chain: Chain, blocks) -> Chain:
    for b in blocks[1:]:
        chain.add_block(b, now=b["timestamp"] + LATER)
    return chain


def same_chain(test, a: Chain, b: Chain) -> None:
    test.assertEqual(a.height, b.height)
    test.assertEqual(a.tip, b.tip)
    test.assertEqual(a.state.state_root(), b.state.state_root())
    test.assertEqual(a.cumulative_work(), b.cumulative_work())
    test.assertEqual(a.tx_index, b.tx_index)
    test.assertEqual(a.headers(), b.headers())


def write_genesis(d: str, genesis: dict) -> str:
    path = os.path.join(d, "genesis.json")
    with open(path, "w") as f:
        json.dump(genesis, f)
    return path


class UndoTests(unittest.TestCase):
    def test_each_block_can_be_undone_exactly(self):
        h = busy_harness()
        c = Chain(h.chain.genesis)
        roots = [c.state.state_root()]
        for b in h.chain.blocks[1:]:
            c.add_block(b, now=b["timestamp"] + LATER)
            roots.append(c.state.state_root())
        self.assertEqual(roots[-1], h.chain.state.state_root())
        for height in range(c.height, 0, -1):
            c.state.undo(c._undo.pop())
            self.assertEqual(c.state.state_root(), roots[height - 1], f"undo of block {height}")
            c.state.check_invariant()

    def test_state_survives_a_trip_through_json(self):
        st = busy_harness().chain.state
        again = State.from_dict(json.loads(canonical_json(st.to_dict())), st.profile)
        self.assertEqual(again.to_dict(), st.to_dict())
        self.assertEqual(again.state_root(), st.state_root())
        again.check_invariant()

    def test_reorg_gives_the_state_of_the_other_branch_and_requeues_our_transactions(self):
        h = busy_harness()
        shared = h.chain.height
        other = copy_into(Chain(h.chain.genesis), h.chain.blocks)
        a, b = h.founders[0], h.founders[1]
        paid = h.send(a, T.TRANSFER, {"to": b.address, "amount": B(1)})
        h.mine(2)                                               # our branch: two blocks, one carrying a payment
        waiting = h.send(b, T.TRANSFER, {"to": a.address, "amount": B(3)})
        mine_alone(other, Wallet.create("o").address, 4, h.t)   # their branch: four blocks, no payment
        work = other.cumulative_work()
        self.assertTrue(h.chain.replace_with(other.blocks))
        same_chain(self, h.chain, other)
        self.assertEqual(h.chain.cumulative_work(), work)
        self.assertEqual(list(h.chain.mempool), [paid, waiting])   # what our blocks carried, then what was waiting
        self.assertEqual(h.chain.get_tx(paid)["status"], "pending")
        h.t += 10
        h.mine()
        self.assertEqual(h.chain.get_tx(paid)["status"], "confirmed")
        self.assertEqual(h.chain.get_tx(waiting)["height"], shared + 5)
        fresh = copy_into(Chain(h.chain.genesis), h.chain.blocks)
        same_chain(self, h.chain, fresh)

    def _branch_ending_in_a_bad_block(self, h: Harness, good: int) -> list[dict]:
        other = copy_into(Chain(h.chain.genesis), h.chain.blocks)
        miner = Wallet.create("o").address
        t = mine_alone(other, miner, good, h.t)
        bad = other.block_template(miner, t + 1)
        bad["txs"][0]["payload"]["amount"] += 1                 # inflated coinbase: fine headers, invalid body
        bad["merkle_root"] = Bk.merkle_root([T.txid(x) for x in bad["txs"]])
        Bk.mine(bad)
        return other.blocks[:] + [bad]

    def test_a_branch_that_turns_out_invalid_leaves_everything_as_it_was(self):
        h = busy_harness()
        branch = self._branch_ending_in_a_bad_block(h, good=3)
        h.send(h.founders[0], T.TRANSFER, {"to": h.founders[1].address, "amount": B(1)})
        h.mine(2)
        before = copy_into(Chain(h.chain.genesis), h.chain.blocks)
        with self.assertRaises(BlockError):
            h.chain.replace_with(branch)
        same_chain(self, h.chain, before)
        h.chain.state.check_invariant()
        h.mine()                                                # and it carries on from there
        self.assertEqual(h.chain.height, before.height + 1)


class DiskStoreTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.d = tmp.name
        self.h = busy_harness()
        self.genesis = self.h.chain.genesis

    def open(self) -> Chain:
        return Chain.open(self.genesis, self.d)

    def test_round_trip(self):
        c = copy_into(self.open(), self.h.chain.blocks)
        c.persist()
        same_chain(self, c, self.h.chain)
        again = self.open()
        same_chain(self, again, self.h.chain)
        self.assertEqual(again.blocks[2:5], self.h.chain.blocks[2:5])
        self.assertEqual(list(again.blocks), list(self.h.chain.blocks))
        self.assertEqual(again.blocks[-1], self.h.chain.tip)
        with self.assertRaises(IndexError):
            again.blocks[again.height + 1]
        for tid, (height, i) in self.h.chain.tx_index.items():
            self.assertEqual(again.get_tx(tid), self.h.chain.get_tx(tid))
        self.h.send(self.h.founders[0], T.TRANSFER, {"to": self.h.founders[1].address, "amount": 1})
        again.add_block(self.h.mine(), now=self.h.t + LATER)    # and it goes on taking blocks
        same_chain(self, self.open(), self.h.chain)

    def test_torn_last_line_is_cut(self):
        copy_into(self.open(), self.h.chain.blocks).persist()
        path = os.path.join(self.d, BLOCKS_FILE)
        size = os.path.getsize(path)
        with open(path, "ab") as f:
            f.write(b'{"hash": "00ab", "height": ')            # a crash mid-write
        logged = []
        again = Chain.open(self.genesis, self.d, logged.append)
        same_chain(self, again, self.h.chain)
        self.assertEqual(os.path.getsize(path), size)
        self.assertTrue(any("cut back" in m for m in logged), logged)

    def test_a_block_that_does_not_check_out_ends_the_file(self):
        copy_into(self.open(), self.h.chain.blocks).persist()
        path = os.path.join(self.d, BLOCKS_FILE)
        with open(path, "rb") as f:
            lines = f.read().split(b"\n")[:-1]
        blk = json.loads(lines[4])
        blk["txs"][0]["payload"]["amount"] += 1                 # no longer what the merkle root commits to
        lines[4] = canonical_json(blk)
        with open(path, "wb") as f:
            f.write(b"\n".join(lines) + b"\n")
        again = self.open()
        self.assertEqual(again.height, 3)
        expect = copy_into(Chain(self.genesis), self.h.chain.blocks[:4])
        same_chain(self, again, expect)
        copy_into(again, self.h.chain.blocks[3:])               # peers fill the gap
        same_chain(self, self.open(), self.h.chain)

    def test_a_file_that_is_not_a_chain_is_kept_aside(self):
        with open(os.path.join(self.d, BLOCKS_FILE), "wb") as f:
            f.write(b"not a block file\n")
        c = self.open()
        self.assertEqual(c.height, 0)
        self.assertTrue(os.path.exists(os.path.join(self.d, BLOCKS_FILE + ".unreadable")))
        same_chain(self, copy_into(c, self.h.chain.blocks), self.h.chain)

    def test_reorg_on_disk(self):
        c = copy_into(self.open(), self.h.chain.blocks)
        other = copy_into(Chain(self.genesis), self.h.chain.blocks)
        self.h.mine(2)
        copy_into(c, self.h.chain.blocks[-3:])
        mine_alone(other, Wallet.create("o").address, 5, self.h.t)
        self.assertTrue(c.replace_with(other.blocks))
        same_chain(self, c, other)
        same_chain(self, self.open(), other)                    # the file holds the new branch, not the old one


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.d = tmp.name
        self.h = busy_harness()
        self.h.mine(17)
        self.genesis = self.h.chain.genesis
        patcher = mock.patch.object(chain_mod, "SNAPSHOT_EVERY", 5)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.c = Chain.open(self.genesis, self.d)
        for b in self.h.chain.blocks[1:]:
            self.c.add_block(b, now=b["timestamp"] + LATER)
            self.c.persist()

    def snapshots(self) -> list[int]:
        return [h for h, _ in self.c._snapshots()]

    def test_restart_from_a_snapshot(self):
        tip = self.c.height
        self.assertGreaterEqual(tip, 15)
        self.assertEqual(self.snapshots(), [h for h in range(5, tip + 1, 5)][-chain_mod.SNAPSHOTS_KEPT:])
        logged = []
        again = Chain.open(self.genesis, self.d, logged.append)
        same_chain(self, again, self.h.chain)
        # no snapshot is MAX_REORG_DEPTH behind the tip yet: the oldest one gives the most undo records
        self.assertIn(f"state from block {self.snapshots()[0]}", logged[-1])
        self.assertEqual(len(again._undo), tip - self.snapshots()[0])
        with mock.patch.dict(os.environ, {"BERRY_FULL_REPLAY": "1"}):
            full = Chain.open(self.genesis, self.d, logged.append)
        same_chain(self, full, self.h.chain)
        self.assertIn("state from genesis", logged[-1])

    def test_a_damaged_snapshot_is_passed_over(self):
        first = self.c._snapshots()[0][1]
        with open(first, "r+b") as f:
            f.seek(os.path.getsize(first) // 2)
            f.write(b"XXXX")
        logged = []
        again = Chain.open(self.genesis, self.d, logged.append)
        same_chain(self, again, self.h.chain)
        self.assertIn(f"state from block {self.snapshots()[1]}", logged[-1])
        for _, path in self.c._snapshots():                     # none usable: genesis it is
            with open(path, "wb") as f:
                f.write(b"{}\n{}\n")
        same_chain(self, Chain.open(self.genesis, self.d, logged.append), self.h.chain)
        self.assertIn("state from genesis", logged[-1])

    def test_reorg_deeper_than_the_undo_records_rebuilds_from_a_snapshot(self):
        for depth, base in ((7, 15), (13, 0)):                  # from a snapshot below the fork; from genesis
            with self.subTest(depth=depth), tempfile.TemporaryDirectory() as d:
                for name in os.listdir(self.d):
                    with open(os.path.join(self.d, name), "rb") as src, open(os.path.join(d, name), "wb") as dst:
                        dst.write(src.read())
                again = Chain.open(self.genesis, d)
                if depth <= len(again._undo):
                    again._undo.clear()                         # as after an earlier reorg used them up
                common = again.height - depth
                self.assertEqual(again._base_state(common)[1], base)
                other = copy_into(Chain(self.genesis), self.h.chain.blocks[:common + 1])
                mine_alone(other, Wallet.create("o").address, depth + 2, self.h.t)
                self.assertTrue(again.replace_with(other.blocks))
                same_chain(self, again, other)
                self.assertTrue(all(h <= common for h, _ in again._snapshots()))
                again.persist()
                same_chain(self, Chain.open(self.genesis, d), other)

    def test_a_failed_deep_reorg_restores_the_chain(self):
        again = Chain.open(self.genesis, self.d)
        again._undo.clear()
        common = again.height - 7
        other = copy_into(Chain(self.genesis), self.h.chain.blocks[:common + 1])
        miner = Wallet.create("o").address
        t = mine_alone(other, miner, 8, self.h.t)
        bad = other.block_template(miner, t + 1)
        bad["txs"][0]["payload"]["amount"] += 1
        bad["merkle_root"] = Bk.merkle_root([T.txid(x) for x in bad["txs"]])
        Bk.mine(bad)
        with self.assertRaises(BlockError):
            again.replace_with(other.blocks[:] + [bad])
        same_chain(self, again, self.h.chain)
        same_chain(self, Chain.open(self.genesis, self.d), self.h.chain)


class LegacyFileTests(unittest.TestCase):
    """A data directory left by a version that kept the whole chain in chain.json."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.d = tmp.name
        self.h = busy_harness()
        self.gpath = write_genesis(self.d, self.h.chain.genesis)
        self.legacy = os.path.join(self.d, "chain.json")

    def start(self) -> Chain:
        with mock.patch("builtins.print"):
            return open_or_create(self.gpath, self.d)

    def test_chain_json_is_taken_over_once(self):
        self.h.chain.save(self.legacy)
        c = self.start()
        same_chain(self, c, self.h.chain)
        self.assertFalse(os.path.exists(self.legacy))
        self.assertTrue(os.path.exists(os.path.join(self.d, "chain-migrated.json")))
        self.assertTrue(os.path.exists(os.path.join(self.d, BLOCKS_FILE)))
        same_chain(self, self.start(), self.h.chain)            # from the block file now
        # the old version ran again for a while (chain-migrated.json renamed back): only the new blocks come over
        self.h.mine(3)
        self.h.chain.save(self.legacy)
        same_chain(self, self.start(), self.h.chain)
        # a chain.json that is behind the block file changes nothing
        behind = copy_into(Chain(self.h.chain.genesis), self.h.chain.blocks[:5])
        behind.save(self.legacy)
        same_chain(self, self.start(), self.h.chain)
        self.assertFalse(os.path.exists(self.legacy))

    def test_when_the_two_disagree_the_one_with_more_work_is_kept(self):
        base = self.h.chain.height
        self.h.chain.save(self.legacy)
        self.start()
        heavy = copy_into(Chain(self.h.chain.genesis), self.h.chain.blocks)
        light = copy_into(Chain(self.h.chain.genesis), self.h.chain.blocks)
        self.h.mine(2)                                          # the block file goes on to base + 2
        node_chain = self.start()
        copy_into(node_chain, self.h.chain.blocks[-3:])
        node_chain.persist()
        mine_alone(light, Wallet.create("l").address, 1, self.h.t)
        mine_alone(heavy, Wallet.create("o").address, 4, self.h.t)
        light.save(self.legacy)
        same_chain(self, self.start(), self.h.chain)            # lighter chain.json: the block file stands
        heavy.save(self.legacy)
        c = self.start()
        same_chain(self, c, heavy)                              # heavier chain.json: it is the chain
        self.assertEqual(c.height, base + 4)
        self.assertEqual(len([n for n in os.listdir(self.d) if n.startswith("blocks-stale-")]), 1)
        same_chain(self, self.start(), heavy)

    def test_a_bad_block_in_chain_json_keeps_what_came_before_it(self):
        blocks = [dict(b) for b in self.h.chain.blocks]
        blocks[6]["nonce"] += 1
        with open(self.legacy, "w") as f:
            json.dump({"genesis": self.h.chain.genesis, "blocks": blocks}, f)
        c = self.start()
        self.assertEqual(c.height, 5)
        same_chain(self, c, copy_into(Chain(self.h.chain.genesis), self.h.chain.blocks[:6]))

    def test_block_file_of_another_genesis_is_set_aside(self):
        self.h.chain.save(self.legacy)
        self.start()
        other = Harness(founders=False)
        write_genesis(self.d, other.chain.genesis)
        c = self.start()
        self.assertEqual(c.height, 0)
        self.assertEqual(c.blocks[0]["hash"], other.chain.blocks[0]["hash"])
        names = os.listdir(self.d)
        self.assertEqual(len([n for n in names if n.startswith("blocks-stale-")]), 1)   # kept, not deleted
        self.assertFalse([n for n in names if n.startswith("state-")])

    def test_node_persist_writes_the_block_file_not_chain_json(self):
        c = self.start()
        node = Node(c, self.d)
        node.mine(Wallet.create("m").address, 3)
        self.assertFalse(os.path.exists(self.legacy))
        again = self.start()
        self.assertEqual(again.height, 3)
        self.assertEqual(again.tip, c.tip)


class SyncTests(unittest.TestCase):
    def test_fork_point_is_found_exactly(self):
        """Walking back in growing steps overshoots the fork; the limit on reorg depth is for the real depth."""
        genesis = Harness(founders=False).chain.genesis
        m, o = Wallet.create("m").address, Wallet.create("o").address
        mine = Chain(genesis)
        t = mine_alone(mine, m, 200, 1_700_000_000)
        peer = copy_into(Chain(genesis), mine.blocks)
        mine_alone(mine, m, 70, t)                              # the steps back land 127 blocks down, not 70
        mine_alone(peer, o, 80, t)
        node = Node(mine, None, ["http://peer"])
        node._http = FakePeerTransport(peer)
        self.assertTrue(node._sync_from("http://peer"))
        self.assertEqual(mine.tip, peer.tip)
        self.assertEqual(mine.state.state_root(), peer.state.state_root())
        self.assertEqual(mine.refused_reorgs, 0)
        calls = node._http.calls
        self.assertTrue(any(u.startswith("http://peer/blocks?from=201&") for u in calls))
        self.assertFalse(any(u.startswith("http://peer/blocks?from=1&") for u in calls), "only the other branch is fetched")
        self.assertTrue(any(u.startswith("http://peer/headers?from=201&to=280") for u in calls))


class LockFreeReadTests(unittest.TestCase):
    def test_reads_do_not_wait_for_the_chain_lock(self):
        """A letter check must answer while a block is being applied (the lock is held)."""
        from http.server import ThreadingHTTPServer
        h = busy_harness()
        a, b = h.founders[0], h.founders[1]
        tid = h.send(a, T.TRANSFER, {"to": b.address, "amount": 1})
        node = Node(h.chain)
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(node))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_address[1]}"
        held, release = threading.Event(), threading.Event()

        def hold():
            with h.chain.lock:
                held.set()
                release.wait(30)

        t = threading.Thread(target=hold, daemon=True)
        t.start()
        self.addCleanup(t.join)
        self.addCleanup(release.set)
        self.assertTrue(held.wait(5))

        def get(path):
            with urllib.request.urlopen(base + path, timeout=5) as r:
                return json.loads(r.read())

        self.assertEqual(get("/status")["height"], h.chain.height)
        self.assertEqual([T.txid(x) for x in get("/mempool")["txs"]], [tid])
        self.assertEqual(get(f"/letters?to={b.address}&pending=1")["letters"], [])
        self.assertEqual(get(f"/balance/{a.address}")["next_nonce"], h.chain.state.nonce(a.address) + 1)
        self.assertEqual(get(f"/account/{a.address}")["address"], a.address)
        self.assertEqual(get(f"/tx/{tid}")["status"], "pending")
        self.assertEqual(get(f"/block/{h.chain.height}")["hash"], h.chain.tip["hash"])
        self.assertEqual(get(f"/block/{h.chain.tip['hash']}")["height"], h.chain.height)
        for missing in (f"/letter/{'ab' * 32}", f"/block/{h.chain.height + 1}", f"/block/{'cd' * 32}"):
            with self.assertRaises(urllib.error.HTTPError) as e:
                get(missing)
            self.assertEqual(e.exception.code, 404)
            e.exception.close()


if __name__ == "__main__":
    unittest.main()
