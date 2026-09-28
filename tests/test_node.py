"""Node-to-node sync, exercised in-process by replacing the HTTP transport
with a fake that serves another Chain. Covers the case that bit the launch
miner: a node that mined its own fork must adopt a heavier peer chain."""

import os
import sys
import unittest
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from berrychain import params  # noqa: E402
from berrychain.chain import Chain  # noqa: E402
from berrychain.node import Node, make_handler  # noqa: E402
from berrychain.wallet import Wallet  # noqa: E402
from test_chain import Harness  # noqa: E402


class FakePeerTransport:
    """Serves /status, /headers and /blocks from a Chain, like a real node."""

    def __init__(self, chain: Chain):
        self.chain = chain
        self.calls = []

    def __call__(self, url, data=None, timeout=5.0, admin=False, max_bytes=0):
        self.calls.append(url)
        u = urlparse(url)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        c = self.chain
        if u.path == "/status":
            return {"chain_id": c.profile["chain_id"], "height": c.height, "tip_hash": c.tip["hash"],
                    "work": c.cumulative_work(), "peers": []}
        if u.path == "/headers":
            lo = max(0, int(q.get("from", 0)))
            hi = min(int(q.get("to", c.height)), lo + params.MAX_HEADERS_PER_REQUEST - 1, c.height)
            return {"headers": c.headers(lo, hi), "height": c.height}
        if u.path == "/blocks":
            lo = max(0, int(q.get("from", 0)))
            hi = min(int(q.get("to", c.height)), lo + params.MAX_BLOCKS_PER_REQUEST - 1, c.height)
            return {"blocks": c.blocks[lo:hi + 1]}
        raise AssertionError(f"unexpected request {url}")


def mine_alone(chain: Chain, miner: str, n: int, t0: int) -> int:
    t = t0
    for _ in range(n):
        t += 1
        assert chain.mine_block(miner, timestamp=t) is not None
    return t


class SyncTests(unittest.TestCase):
    def test_forked_node_adopts_heavier_peer_chain(self):
        h = Harness(founders=False)
        genesis = h.chain.genesis
        miner = Wallet.create("m").address
        peer = Chain(genesis)
        mine_alone(peer, miner, 40, 1_700_000_000)         # the network
        mine = Chain(genesis)
        mine_alone(mine, miner, 12, 1_700_000_000)         # a node that mined alone from the same genesis
        self.assertNotEqual(mine.tip["hash"], peer.tip["hash"])
        node = Node(mine, None, ["http://peer"])
        node._http = FakePeerTransport(peer)
        self.assertTrue(node._sync_from("http://peer"))
        self.assertEqual(mine.height, 40)
        self.assertEqual(mine.tip["hash"], peer.tip["hash"])
        # the walk back must have looked at genesis, the only shared block
        self.assertIn("http://peer/headers?from=0&to=0", node._http.calls)

    def test_node_behind_on_same_chain_extends(self):
        h = Harness(founders=False)
        genesis = h.chain.genesis
        miner = Wallet.create("m").address
        peer = Chain(genesis)
        t = mine_alone(peer, miner, 25, 1_700_000_000)
        mine = Chain(genesis)
        for b in peer.blocks[1:11]:
            mine.add_block(b, now=b["timestamp"] + 10_000)
        node = Node(mine, None, ["http://peer"])
        node._http = FakePeerTransport(peer)
        self.assertTrue(node._sync_from("http://peer"))
        self.assertEqual(mine.tip["hash"], peer.tip["hash"])

    def test_lighter_peer_is_ignored(self):
        h = Harness(founders=False)
        genesis = h.chain.genesis
        miner = Wallet.create("m").address
        peer = Chain(genesis)
        mine_alone(peer, miner, 5, 1_700_000_000)
        mine = Chain(genesis)
        mine_alone(mine, miner, 30, 1_700_000_000)
        node = Node(mine, None, ["http://peer"])
        node._http = FakePeerTransport(peer)
        self.assertFalse(node._sync_from("http://peer"))
        self.assertEqual(mine.height, 30)

    def test_different_genesis_is_refused(self):
        a, b = Harness(founders=False), Harness(founders=False)
        miner = Wallet.create("m").address
        peer = Chain(b.chain.genesis)
        mine_alone(peer, miner, 20, 1_700_000_000)
        mine = Chain(a.chain.genesis)
        mine_alone(mine, miner, 3, 1_700_000_000)
        node = Node(mine, None, ["http://peer"])
        node._http = FakePeerTransport(peer)
        self.assertFalse(node._sync_from("http://peer"))
        self.assertEqual(mine.height, 3)


class PersistenceTests(unittest.TestCase):
    def test_empty_or_truncated_chain_file_is_set_aside(self):
        import json, os, tempfile
        from berrychain.node import open_or_create
        h = Harness(founders=False)
        with tempfile.TemporaryDirectory() as d:
            gpath = os.path.join(d, "genesis.json")
            with open(gpath, "w") as f:
                json.dump(h.chain.genesis, f)
            path = os.path.join(d, "chain.json")
            open(path, "w").close()                                    # what a crash mid-save can leave behind
            chain = open_or_create(gpath, d)
            self.assertEqual(chain.height, 0)
            self.assertFalse(os.path.exists(path))
            self.assertTrue(any(n.startswith("chain-corrupt-") for n in os.listdir(d)))
            with open(path, "w") as f:
                f.write('{"genesis": {')                                 # truncated
            chain = open_or_create(gpath, d)
            self.assertEqual(chain.height, 0)
            chain.save(path)                                             # a good save round-trips
            self.assertEqual(open_or_create(gpath, d).tip["hash"], chain.tip["hash"])


if __name__ == "__main__":
    unittest.main()


class HttpTests(unittest.TestCase):
    """The HTTP face of a node: browsers preflight a JSON POST with OPTIONS and
    need the CORS headers back, or the letterbox in a browser cannot send."""

    def test_options_preflight_and_cors_headers(self):
        import http.client
        import threading
        from http.server import ThreadingHTTPServer
        h = Harness(founders=1)
        node = Node(h.chain)
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(node))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        port = server.server_address[1]
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.request("OPTIONS", "/tx", headers={"Origin": "https://berrychain.link", "Access-Control-Request-Method": "POST",
                                            "Access-Control-Request-Headers": "content-type"})
        r = c.getresponse()
        r.read()
        self.assertEqual(r.status, 204)
        self.assertEqual(r.getheader("Access-Control-Allow-Origin"), "*")
        self.assertIn("POST", r.getheader("Access-Control-Allow-Methods"))
        self.assertIn("Content-Type", r.getheader("Access-Control-Allow-Headers"))
        c.request("GET", "/status", headers={"Origin": "https://berrychain.link"})
        r = c.getresponse()
        body = r.read()
        self.assertEqual(r.status, 200)
        self.assertEqual(r.getheader("Access-Control-Allow-Origin"), "*")
        self.assertIn(b'"height"', body)
