"""
Client-side checks that run against an in-process chain, no HTTP needed.

FakeNode wires BerryClient straight to a Chain and lets a test play a hostile
node that rewrites what the client sees. The seller must never wrap a packet
key to anyone but the buyer who signed the purchase.
"""

import copy
import os
import sys
import unittest
import warnings
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from berrychain import crypto, tx as T  # noqa: E402
from berrychain.client import BerryClient, ClientError, node_is_trusted  # noqa: E402
from berrychain.state import TxError  # noqa: E402
from berrychain.wallet import Wallet  # noqa: E402
from test_chain import Harness  # noqa: E402


class FakeNode(BerryClient):
    """BerryClient over an in-process Chain. `tamper(path, response)` may
    return an altered response, exactly as a hostile node could."""

    def __init__(self, chain, tamper=None):
        self.chain = chain
        self.tamper = tamper or (lambda path, obj: obj)
        self.submitted = []
        super().__init__("http://127.0.0.1:1")

    def _req(self, path, data=None):
        c, st = self.chain, self.chain.state
        u = urlparse(path)
        parts = [p for p in u.path.split("/") if p]
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        head, arg = parts[0], (parts[1] if len(parts) > 1 else None)
        if data is not None:
            self.submitted.append(copy.deepcopy(data))
            try:
                return {"txid": c.add_tx(data)}
            except TxError as e:
                raise ClientError(str(e)) from None
        if head == "status":
            out = {"chain_id": c.profile["chain_id"], "height": c.height}
        elif head == "balance":
            out = {"balance": st.balance(arg), "nonce": st.nonce(arg)}
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
        return self.tamper(path, out)


class Setup:
    def __init__(self, tamper=None):
        self.h = Harness()
        self.seller, self.buyer, self.attacker = self.h.founders[0], self.h.founders[1], self.h.founders[2]
        self.node = FakeNode(self.h.chain, tamper)
        self.content = b"the answer is 42"
        self.pid = self.node.list_packet(self.seller, self.content, "Answer", price_berry="1")
        self.h.mine()
        self.eid = self.node.buy_packet(self.buyer, self.pid)
        self.h.mine()


class DeliveryTrustTests(unittest.TestCase):
    def test_honest_node_round_trip(self):
        s = Setup()
        ids = s.node.deliver_all(s.seller)
        self.assertEqual(len(ids), 1)
        s.h.mine()
        self.assertEqual(s.node.redeem(s.buyer, s.eid), s.content)
        with self.assertRaises(Exception):
            crypto.unwrap_from_sender(s.attacker.enc_priv, s.h.chain.state.escrows[s.eid]["wrapped_key"])

    def test_refuses_escrow_with_swapped_buyer_key(self):
        """The node rewrites the escrow's buyer_enc_pub to the attacker's key."""
        s = Setup()

        def tamper(path, obj):
            if path.startswith("/escrow"):
                for e in ([obj] if "id" in obj else obj["escrows"]):
                    e["buyer_enc_pub"] = s.attacker.enc_pub
            return obj
        s.node.tamper = tamper
        with self.assertRaises(ClientError) as cm:
            s.node.deliver_all(s.seller)
        self.assertIn("disagrees with the buyer's signed purchase", str(cm.exception))
        self.assertEqual([t for t in s.node.submitted if t["type"] == T.DELIVER_PACKET], [])
        self.assertEqual(s.h.chain.state.escrows[s.eid]["status"], "pending")

    def test_refuses_purchase_tx_not_signed_by_buyer(self):
        """The node swaps the escrow to the attacker AND serves a purchase tx
        the attacker signed. The txid no longer matches the escrow id."""
        s = Setup()
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
        self.assertEqual([t for t in s.node.submitted if t["type"] == T.DELIVER_PACKET], [])

    def test_refuses_tampered_signature_or_payload(self):
        s = Setup()
        real = copy.deepcopy(s.h.chain.get_tx(s.eid)["tx"])
        cases = []
        bad = copy.deepcopy(real); bad["payload"]["enc_pub"] = s.attacker.enc_pub; cases.append(bad)   # sig no longer valid
        bad = copy.deepcopy(real); bad["sig"] = "00" * 64; cases.append(bad)
        bad = copy.deepcopy(real); bad["pubkey"] = s.attacker.sign_pub; cases.append(bad)
        for tx in cases:
            s.node.tamper = lambda path, obj, tx=tx: ({**obj, "tx": tx} if path.startswith("/tx/") else obj)
            with self.assertRaises(ClientError):
                s.node.deliver_all(s.seller)
        self.assertEqual([t for t in s.node.submitted if t["type"] == T.DELIVER_PACKET], [])

    def test_refuses_to_deliver_someone_elses_sale(self):
        s = Setup()
        with self.assertRaises(ClientError):
            s.node.deliver(s.attacker, s.eid)


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
            Quiet("http://seed.example.org:8801")
            self.assertTrue(any("plain HTTP" in str(x.message) for x in w))
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            Quiet("http://127.0.0.1:8801")
            self.assertEqual(w, [])


if __name__ == "__main__":
    unittest.main()
