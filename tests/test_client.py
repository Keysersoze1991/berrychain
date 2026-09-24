"""
Client-side checks that run against an in-process chain, no HTTP needed.

FakeNode wires BerryClient straight to a Chain and lets a test play a hostile
node that rewrites what the client sees, or serves a different chain
altogether. The seller must never wrap a packet key to anyone but a buyer
whose purchase is buried in the heaviest chain under real proof-of-work.
"""

import copy
import os
import sys
import tempfile
import unittest
import warnings
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from berrychain import crypto, params, tx as T  # noqa: E402
from berrychain.chain import Chain  # noqa: E402
from berrychain.client import BerryClient, ClientError, node_is_trusted  # noqa: E402
from berrychain.lightclient import LightClient, VerifyError  # noqa: E402
from berrychain.state import TxError  # noqa: E402
from test_chain import Harness  # noqa: E402


class FakeNode(BerryClient):
    """BerryClient over an in-process Chain. `tamper(path, response)` may
    return an altered response, exactly as a hostile node could. `chain` can
    be swapped for another Chain to play a node on a different fork."""

    def __init__(self, chain, tamper=None, **kw):
        self.chain = chain
        self.tamper = tamper or (lambda path, obj: obj)
        self.submitted = []
        kw.setdefault("verify", True)
        super().__init__("http://127.0.0.1:1", **kw)

    def _req(self, path, data=None):
        if data is not None:
            self.submitted.append(copy.deepcopy(data))
            try:
                return {"txid": self.chain.add_tx(data)}
            except TxError as e:
                raise ClientError(str(e)) from None
        try:
            out = self._route(path)
        except ClientError:
            out = self.tamper(path, None)       # a liar can answer what the chain cannot
            if out is None:
                raise
            return out
        return self.tamper(path, out)

    def _route(self, path):
        c, st = self.chain, self.chain.state
        u = urlparse(path)
        parts = [p for p in u.path.split("/") if p]
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        head, arg = parts[0], (parts[1] if len(parts) > 1 else None)
        if head == "status":
            out = {"chain_id": c.profile["chain_id"], "profile": c.profile_name, "height": c.height,
                   "tip_hash": c.tip["hash"], "work": c.cumulative_work(), "letter_fee": st.letter_fee()}
        elif head == "balance":
            pending = sum(1 for t in c.mempool.values() if t.get("from") == arg)
            out = {"balance": st.balance(arg), "nonce": st.nonce(arg), "next_nonce": st.nonce(arg) + pending}
        elif head == "account":
            out = {"address": arg, "balance": st.balance(arg), "nonce": st.nonce(arg), "llm": copy.deepcopy(st.llms.get(arg)),
                   "reputation": st.reputation.get(arg), "correspondents": st.correspondents(arg), "is_registrar": arg in st.registrars}
        elif head == "packets":
            items = [copy.deepcopy(p) for p in st.packets.values() if p["active"]]
            if q.get("seller"):
                items = [p for p in items if p["seller"] == q["seller"]]
            if q.get("tag"):
                items = [p for p in items if q["tag"] in p["tags"]]
            out = {"packets": items}
        elif head == "block":
            h = int(arg)
            if h > c.height:
                raise ClientError("no such block")
            out = copy.deepcopy(c.blocks[h])
        elif head == "headers":
            lo = max(0, int(q.get("from", 0)))
            hi = min(int(q.get("to", c.height)), lo + params.MAX_HEADERS_PER_REQUEST - 1, c.height)
            out = {"headers": copy.deepcopy(c.headers(lo, hi)), "height": c.height}
        elif head == "escrow":
            if arg not in st.escrows:
                raise ClientError("no such escrow")
            out = copy.deepcopy(st.escrows[arg])
        elif head == "escrows":
            items = [copy.deepcopy(e) for e in st.escrows.values()]
            for k in ("buyer", "seller", "status", "packet_id"):
                if q.get(k):
                    items = [e for e in items if e[k] == q[k]]
            out = {"escrows": items}
        elif head == "params":
            out = {"starter_claim_work_bits": c.profile.get("starter_claim_work_bits", 0),
                   "starter_amount": st.grant_amount("starter", c.height + 1), "min_fee": params.MIN_FEE,
                   "current_amounts": {t: st.grant_amount(t, c.height + 1) for t in params.GRANT_TIERS}}
        elif head == "letters":
            items = [copy.deepcopy(l) for l in st.letters.values()]
            for k in ("to", "from"):
                if q.get(k):
                    items = [l for l in items if l[k] == q[k]]
            if q.get("since"):
                items = [l for l in items if l["height"] >= int(q["since"])]
            out = {"letters": items}
        elif head == "letter":
            if arg not in st.letters:
                raise ClientError("no such letter")
            out = dict(copy.deepcopy(st.letters[arg]), ciphertext=c.get_ciphertext(arg))
        elif head == "tx":
            r = c.get_tx(arg)
            if not r:
                raise ClientError("unknown txid")
            out = copy.deepcopy(r)
        elif head == "packet":
            p = copy.deepcopy(st.packets[arg])
            p["ciphertext"] = c.get_ciphertext(arg)
            p["seller_reputation"] = st.reputation.get(p["seller"])
            out = p
        else:
            raise ClientError(f"not found: {path}")
        return out


def delivers(node):
    return [t for t in node.submitted if t["type"] == T.DELIVER_PACKET]


class Setup:
    """Seller lists, buyer buys, one block mined on top. Light client state
    lives in a temp file so persistence can be tested."""

    def __init__(self, tamper=None, **kw):
        self.h = Harness()
        self.seller, self.buyer, self.attacker = self.h.founders[0], self.h.founders[1], self.h.founders[2]
        self.tmp = tempfile.TemporaryDirectory()
        self.headers_path = os.path.join(self.tmp.name, "headers.json")
        kw.setdefault("headers_path", self.headers_path)
        self.kw = kw
        self.node = FakeNode(self.h.chain, tamper, **kw)
        self.content = b"the answer is 42"
        self.pid = self.node.list_packet(self.seller, self.content, "Answer", price_berry="1")
        self.h.mine()
        self.eid = self.node.buy_packet(self.buyer, self.pid)
        self.h.mine()

    def fork_with_fake_purchase(self, extra_blocks: int) -> Chain:
        """An attacker's private fork from genesis: copies the seller's real
        listing, adds the attacker's own purchase, mines `extra_blocks`."""
        other = Chain(self.h.chain.genesis)
        for b in self.h.chain.blocks[1:self.h.setup_height + 1]:     # same founders as the real chain
            other.add_block(b, now=b["timestamp"] + 10_000)
        listing = self.h.chain.get_tx(self.pid)["tx"]
        other.add_tx(listing)
        t = other.tip["timestamp"]
        t += 1; other.mine_block(self.attacker.address, timestamp=t)
        buy = T.build(T.BUY_PACKET, self.attacker.address, other.state.nonce(self.attacker.address), params.MIN_FEE,
                      {"packet_id": self.pid, "enc_pub": self.attacker.enc_pub}, other.profile["chain_id"])
        self.attacker.sign(buy)
        self.fake_eid = other.add_tx(buy)
        for _ in range(extra_blocks):
            t += 1; other.mine_block(self.attacker.address, timestamp=t)
        return other


class Base(unittest.TestCase):
    def make(self, tamper=None, **kw) -> Setup:
        s = Setup(tamper, **kw)
        self.addCleanup(s.tmp.cleanup)
        return s


class DeliveryTrustTests(Base):
    def test_honest_node_round_trip(self):
        s = self.make()
        ids = s.node.deliver_all(s.seller)
        self.assertEqual(len(ids), 1)
        self.assertTrue(os.path.exists(s.headers_path))
        self.assertEqual(s.node.light.height, s.h.chain.height)
        s.h.mine()
        self.assertEqual(s.node.redeem(s.buyer, s.eid), s.content)
        with self.assertRaises(Exception):
            crypto.unwrap_from_sender(s.attacker.enc_priv, s.h.chain.state.escrows[s.eid]["wrapped_key"])

    def test_refuses_escrow_with_swapped_buyer_key(self):
        """The node rewrites the escrow's buyer_enc_pub to the attacker's key."""
        s = self.make()

        def tamper(path, obj):
            if path.startswith("/escrow"):
                for e in ([obj] if "id" in obj else obj["escrows"]):
                    e["buyer_enc_pub"] = s.attacker.enc_pub
            return obj
        s.node.tamper = tamper
        with self.assertRaises(ClientError) as cm:
            s.node.deliver_all(s.seller)
        self.assertIn("disagrees with the buyer's signed purchase", str(cm.exception))
        self.assertEqual(delivers(s.node), [])
        self.assertEqual(s.h.chain.state.escrows[s.eid]["status"], "pending")

    def test_refuses_purchase_tx_not_signed_by_buyer(self):
        """Verification off: the node swaps the escrow to the attacker AND
        serves a purchase tx the attacker signed. Its txid cannot match."""
        s = self.make(verify=False)
        forged = T.build(T.BUY_PACKET, s.attacker.address, 0, 10_000,
                         {"packet_id": s.pid, "enc_pub": s.attacker.enc_pub}, s.h.chain.profile["chain_id"])
        s.attacker.sign(forged)

        def tamper(path, obj):
            if path.startswith("/escrow"):
                for e in ([obj] if "id" in obj else obj["escrows"]):
                    e["buyer"], e["buyer_enc_pub"] = s.attacker.address, s.attacker.enc_pub
            if path.startswith("/tx/"):
                obj["tx"] = forged
            return obj
        s.node.tamper = tamper
        with self.assertRaises(ClientError):
            s.node.deliver_all(s.seller)
        self.assertEqual(delivers(s.node), [])

    def test_refuses_tampered_signature_or_payload(self):
        s = self.make(verify=False)
        real = copy.deepcopy(s.h.chain.get_tx(s.eid)["tx"])
        cases = []
        bad = copy.deepcopy(real); bad["payload"]["enc_pub"] = s.attacker.enc_pub; cases.append(bad)
        bad = copy.deepcopy(real); bad["sig"] = "00" * 64; cases.append(bad)
        bad = copy.deepcopy(real); bad["pubkey"] = s.attacker.sign_pub; cases.append(bad)
        for tx in cases:
            s.node.tamper = lambda path, obj, tx=tx: ({**obj, "tx": tx} if path.startswith("/tx/") else obj)
            with self.assertRaises(ClientError):
                s.node.deliver_all(s.seller)
        self.assertEqual(delivers(s.node), [])

    def test_refuses_to_deliver_someone_elses_sale(self):
        s = self.make()
        with self.assertRaises(ClientError):
            s.node.deliver(s.attacker, s.eid)


class LightClientTests(Base):
    def test_fabricated_purchase_in_unmined_block_is_refused(self):
        """The node invents a purchase and a block for it, but cannot mine."""
        s = self.make()
        forged = T.build(T.BUY_PACKET, s.attacker.address, 0, params.MIN_FEE,
                         {"packet_id": s.pid, "enc_pub": s.attacker.enc_pub}, s.h.chain.profile["chain_id"])
        s.attacker.sign(forged)
        fake_eid = T.txid(forged)
        h = s.h.chain.height
        fake_block = copy.deepcopy(s.h.chain.blocks[h]); fake_block["txs"].append(forged)
        fake_escrow = {**s.h.chain.state.escrows[s.eid], "id": fake_eid, "buyer": s.attacker.address, "buyer_enc_pub": s.attacker.enc_pub}

        def tamper(path, obj):
            if path.startswith("/escrows"):
                obj["escrows"] = [fake_escrow]
            if path == f"/escrow/{fake_eid}":
                return fake_escrow
            if path == f"/tx/{fake_eid}":
                return {"tx": forged, "height": h, "index": 1, "status": "confirmed"}
            if path == f"/block/{h}":
                return fake_block
            return obj
        s.node.tamper = tamper
        with self.assertRaises(ClientError) as cm:
            s.node.deliver_all(s.seller)
        self.assertIn("chain verification failed", str(cm.exception))
        self.assertEqual(delivers(s.node), [])

    def test_lighter_fork_is_refused_once_real_chain_seen(self):
        """After syncing the real chain, a node on the attacker's shorter
        private fork (which contains a real-looking purchase) is refused."""
        s = self.make()
        s.h.mine(3)
        s.node.light.sync(s.node)                         # seller has seen the real chain
        real_height = s.node.light.height
        s.node.chain = s.fork_with_fake_purchase(extra_blocks=1)   # fork is shorter than the real chain
        with self.assertRaises(ClientError) as cm:
            s.node.deliver_all(s.seller)
        self.assertIn("lighter chain", str(cm.exception))
        self.assertEqual(delivers(s.node), [])
        self.assertEqual(s.node.light.height, real_height)        # best chain untouched

    def test_heavier_fork_needs_out_mining_and_checkpoint_blocks_it(self):
        """A fork heavier than everything the seller has seen is accepted:
        that is the proof-of-work assumption. A pinned checkpoint on the real
        chain closes even that door."""
        s = self.make()
        real_h = s.h.chain.height
        fork = s.fork_with_fake_purchase(extra_blocks=real_h + 3)       # heavier than the real chain
        s.node.light.sync(s.node)
        s.node.chain = fork
        # without a checkpoint the fork wins and the seller would deliver to the attacker
        s.node.deliver_all(s.seller)
        self.assertEqual(len(delivers(s.node)), 1)
        # with a checkpoint pinned to the real chain, the same fork is refused
        s2 = self.make()
        cp = s2.h.setup_height + 1                                 # first block the fork disagrees on
        s2.node.light.checkpoint = (cp, s2.h.chain.blocks[cp]["hash"])
        fork2 = s2.fork_with_fake_purchase(extra_blocks=s2.h.chain.height + 3)
        s2.node.chain = fork2
        with self.assertRaises(ClientError) as cm:
            s2.node.deliver_all(s2.seller)
        self.assertIn("checkpoint", str(cm.exception))
        self.assertEqual(delivers(s2.node), [])

    def test_pinned_genesis_hash(self):
        s = self.make()
        good = s.h.chain.blocks[0]["hash"]
        FakeNode(s.h.chain, headers_path=os.path.join(s.tmp.name, "g.json"), genesis_hash=good).light.sync(s.node)
        bad = FakeNode(s.h.chain, headers_path=os.path.join(s.tmp.name, "b.json"), genesis_hash="00" * 32)
        with self.assertRaises(VerifyError):
            bad.light.sync(bad)

    def test_confirmation_depth(self):
        s = self.make(min_confirmations=3)                 # purchase block has 1 confirmation so far
        with self.assertRaises(ClientError) as cm:
            s.node.deliver_all(s.seller)
        self.assertIn("confirmation", str(cm.exception))
        s.h.mine(2)
        self.assertEqual(len(s.node.deliver_all(s.seller)), 1)

    def test_invalid_header_refused(self):
        s = self.make()

        def tamper(path, obj):
            if path.startswith("/headers") and obj["headers"] and obj["headers"][-1]["height"] == s.h.chain.height:
                obj["headers"][-1] = {**obj["headers"][-1], "nonce": obj["headers"][-1]["nonce"] + 1}
            return obj
        s.node.tamper = tamper
        with self.assertRaises(ClientError) as cm:
            s.node.deliver_all(s.seller)
        self.assertIn("invalid header", str(cm.exception))

    def test_headers_persist_and_refuse_regression(self):
        s = self.make()
        s.h.mine(4)
        s.node.deliver_all(s.seller)
        height = s.node.light.height
        # a fresh client loads the stored headers and will not accept a shorter chain
        lc = LightClient(s.headers_path)
        self.assertEqual(lc.height, height)
        shorter = Chain(s.h.chain.genesis)
        for b in s.h.chain.blocks[1:s.h.setup_height + 2]:
            shorter.add_block(b, now=b["timestamp"] + 10_000)
        node2 = FakeNode(shorter, headers_path=s.headers_path)
        with self.assertRaises(VerifyError):
            node2.light.sync(node2)

    def test_helper_node_reveals_heavier_chain(self):
        """The primary node hides the real chain behind a short fork, but a
        helper node shows the real one, so the fork is refused."""
        s = self.make()
        s.h.mine(3)
        honest = FakeNode(s.h.chain, verify=False)
        liar = FakeNode(s.fork_with_fake_purchase(extra_blocks=1), headers_path=os.path.join(s.tmp.name, "l.json"))
        liar._verify_clients = [honest]
        with self.assertRaises(ClientError) as cm:
            liar.deliver_all(s.seller)
        self.assertIn("lighter chain", str(cm.exception))


class NodeTrustTests(unittest.TestCase):
    def test_trust_classification(self):
        self.assertTrue(node_is_trusted("http://127.0.0.1:8801"))
        self.assertTrue(node_is_trusted("http://localhost:8801"))
        self.assertTrue(node_is_trusted("https://seed.example.org"))
        self.assertFalse(node_is_trusted("http://seed.example.org:8801"))
        self.assertFalse(node_is_trusted("http://10.0.0.5:8801"))

    def test_untrusted_node_warns(self):
        class Quiet(BerryClient):
            def _req(self, path, data=None):
                return {"chain_id": "berry-dev"}
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            Quiet("http://seed.example.org:8801", verify=False)
            self.assertTrue(any("plain HTTP" in str(x.message) for x in w))
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            Quiet("http://127.0.0.1:8801", verify=False)
            self.assertEqual(w, [])

    def test_from_env(self):
        class Quiet(BerryClient):
            def _req(self, path, data=None):
                return {"chain_id": "berry-dev"}
        old = dict(os.environ)
        try:
            os.environ.update({"BERRY_CHECKPOINT": "12:" + "ab" * 32, "BERRY_MIN_CONFIRMATIONS": "4",
                               "BERRY_VERIFY_NODES": "http://a:1, http://b:2", "BERRY_HEADERS": "x.json"})
            c = Quiet.from_env("http://127.0.0.1:1")
            self.assertEqual(c.light.checkpoint, (12, "ab" * 32))
            self.assertEqual(c.min_confirmations, 4)
            self.assertEqual(c.verify_node_urls, ["http://a:1", "http://b:2"])
            self.assertEqual(c.light.path, "x.json")
            os.environ["BERRY_VERIFY"] = "0"
            self.assertIsNone(Quiet.from_env("http://127.0.0.1:1").light)
        finally:
            os.environ.clear(); os.environ.update(old)


if __name__ == "__main__":
    unittest.main()
