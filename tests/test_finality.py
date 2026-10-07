"""Rolling finality: a node refuses to reorganise away more than
MAX_REORG_DEPTH of its own blocks, however heavy the other fork, while a
node with nothing settled (fresh, or forked shallowly) still takes the
heaviest valid chain."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from berrychain import params  # noqa: E402
from berrychain.chain import Chain, ReorgTooDeep  # noqa: E402
from berrychain.node import Node  # noqa: E402
from berrychain.wallet import Wallet  # noqa: E402
from test_chain import Harness  # noqa: E402
from test_node import FakePeerTransport, mine_alone  # noqa: E402


class FinalityTests(unittest.TestCase):
    def setUp(self):
        self.genesis = Harness(founders=False).chain.genesis
        self.miner = Wallet.create("m").address
        self.other = Wallet.create("o").address

    def forks(self, shared: int, ours: int, theirs: int):
        """Two chains sharing `shared` blocks, then ours mines `ours` alone and theirs `theirs`."""
        t0 = 1_700_000_000
        mine = Chain(self.genesis)
        t = mine_alone(mine, self.miner, shared, t0)
        peer = Chain(self.genesis)
        for b in mine.blocks[1:]:
            peer.add_block(b, now=b["timestamp"] + params.MAX_FUTURE_DRIFT)
        mine_alone(mine, self.miner, ours, t)
        mine_alone(peer, self.other, theirs, t)
        self.assertNotEqual(mine.tip["hash"], peer.tip["hash"])
        return mine, peer

    def test_fork_point(self):
        mine, peer = self.forks(10, 3, 5)
        self.assertEqual(mine.fork_point(peer.blocks), 10)
        self.assertTrue(mine.reorg_allowed(peer.blocks))
        self.assertFalse(mine.reorg_allowed(peer.blocks, max_depth=2))

    def test_shallow_heavier_fork_is_adopted(self):
        mine, peer = self.forks(5, 3, 6)
        self.assertTrue(mine.replace_with(peer.blocks))
        self.assertEqual(mine.tip["hash"], peer.tip["hash"])
        self.assertEqual(mine.refused_reorgs, 0)

    def test_deep_heavier_fork_is_refused(self):
        depth = params.MAX_REORG_DEPTH
        mine, peer = self.forks(2, depth + 1, depth + 4)
        before = mine.tip["hash"]
        with self.assertRaises(ReorgTooDeep):
            mine.replace_with(peer.blocks)
        self.assertEqual(mine.tip["hash"], before)
        self.assertEqual(mine.refused_reorgs, 1)
        # exactly at the limit is still allowed
        mine2, peer2 = self.forks(2, depth, depth + 3)
        self.assertTrue(mine2.replace_with(peer2.blocks))

    def test_sync_does_not_even_download_a_too_deep_fork(self):
        depth = params.MAX_REORG_DEPTH
        mine, peer = self.forks(2, depth + 1, depth + 4)
        node = Node(mine, None, ["http://peer"])
        node._http = FakePeerTransport(peer)
        self.assertFalse(node._sync_from("http://peer"))
        self.assertEqual(mine.height, 2 + depth + 1)
        self.assertEqual(mine.refused_reorgs, 1)
        self.assertFalse(any("/blocks" in u for u in node._http.calls), "bodies must not be fetched for a refused reorg")
        self.assertEqual(node.status()["refused_reorgs"], 1)
        self.assertEqual(node.status()["max_reorg_depth"], depth)

    def test_fresh_node_still_takes_the_heavy_chain(self):
        peer = Chain(self.genesis)
        mine_alone(peer, self.other, params.MAX_REORG_DEPTH + 50, 1_700_000_000)
        fresh = Chain(self.genesis)
        node = Node(fresh, None, ["http://peer"])
        node._http = FakePeerTransport(peer)
        self.assertTrue(node._sync_from("http://peer"))
        self.assertEqual(fresh.tip["hash"], peer.tip["hash"])

    def test_node_far_behind_on_the_same_chain_catches_up(self):
        peer = Chain(self.genesis)
        t = mine_alone(peer, self.other, 5, 1_700_000_000)
        behind = Chain(self.genesis)
        for b in peer.blocks[1:]:
            behind.add_block(b, now=b["timestamp"] + params.MAX_FUTURE_DRIFT)
        mine_alone(peer, self.other, params.MAX_REORG_DEPTH + 30, t)
        node = Node(behind, None, ["http://peer"])
        node._http = FakePeerTransport(peer)
        self.assertTrue(node._sync_from("http://peer"))
        self.assertEqual(behind.tip["hash"], peer.tip["hash"])


if __name__ == "__main__":
    unittest.main()
