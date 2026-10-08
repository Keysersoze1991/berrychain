"""Chain 0.10.0, "sealed post v2": letters bind sender and recipient into the
seal, service-2 grants come from the registrars, self-claimed service-1
grants are capped per window, and the keyless reserve pays out only by
registrar quorum. Devnet activates all of it at height 0; the tests that
need the old rules push the activation out of reach."""

import hashlib
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from berrychain import crypto, params, tx as T  # noqa: E402
from berrychain.client import ClientError, compose_letter, open_letter  # noqa: E402
from berrychain.state import TxError  # noqa: E402
from berrychain.wallet import Wallet  # noqa: E402
from test_chain import B, Harness  # noqa: E402
from test_client import FakeNode  # noqa: E402
from test_correspondence import claim_grant, correspond, newcomers  # noqa: E402

RESERVE = params.RESERVE_ADDRESS


def before_upgrade(h):
    h.chain.profile["sealed_post_activation"] = 10 ** 9
    return h


def sealed_payload(sender: Wallet, to: Wallet, content: bytes, seal: int):
    key = crypto.new_packet_key()
    aad = crypto.letter_aad(sender.address, to.address) if seal == 2 else b""
    ct = crypto.encrypt_packet(key, content, aad)
    p = {"to": to.address, "enc_pub": to.enc_pub, "ciphertext": ct.hex(),
         "ciphertext_hash": hashlib.sha256(ct).hexdigest(), "wrapped_key": crypto.wrap_to_recipient(to.enc_pub, key, aad)}
    if seal != 1:
        p["seal"] = seal
    return p


class SealTests(unittest.TestCase):
    def setUp(self):
        self.h = Harness(founders=3)
        self.alice, self.bob, self.eve = self.h.founders
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.node = FakeNode(self.h.chain, headers_path=os.path.join(self.tmp.name, "headers.json"))

    def test_client_seals_v2_after_activation_and_both_sides_open_it(self):
        self.assertTrue(self.node.sealed_post_active())
        lid = self.node.send_letter(self.alice, self.bob.address, compose_letter("Charts tomorrow.", subject="Tide", sender_name="alice"))
        self.assertEqual(self.node.submitted[-1]["payload"]["seal"], 2)
        self.h.mine()
        self.assertEqual(self.h.chain.state.letters[lid]["seal"], 2)
        self.assertEqual(open_letter(self.node.read_letter(self.bob, lid))["body"], "Charts tomorrow.")
        self.assertEqual(open_letter(self.node.read_letter(self.alice, lid))["body"], "Charts tomorrow.")

    def test_a_copied_letter_under_another_name_does_not_open(self):
        lid = self.node.send_letter(self.alice, self.bob.address, compose_letter("Only from me.", sender_name="alice"))
        self.h.mine()
        stolen = dict(self.h.chain.get_tx(lid)["tx"]["payload"])
        stolen["ciphertext"] = self.h.chain.get_ciphertext(lid)
        # the chain cannot see inside the seal, so eve's re-send is a valid transaction...
        forged = self.h.send(self.eve, T.SEND_LETTER, stolen, fee=self.h.chain.state.letter_fee())
        self.h.mine()
        self.assertIn(forged, self.h.chain.state.letters)
        # ...but bob's app refuses it: the seal was bound to alice -> bob, not eve -> bob
        with self.assertRaises(ClientError) as cm:
            self.node.read_letter(self.bob, forged)
        self.assertIn("does not match the sender and recipient", str(cm.exception))
        self.assertEqual(open_letter(self.node.read_letter(self.bob, lid))["body"], "Only from me.")   # the real one still opens

    def test_chain_refuses_v1_seals_after_activation_and_accepts_them_before(self):
        with self.assertRaises(TxError) as cm:
            self.h.send(self.alice, T.SEND_LETTER, sealed_payload(self.alice, self.bob, b"old app", 1), fee=self.h.chain.state.letter_fee())
        self.assertIn("seal version 2", str(cm.exception))
        with self.assertRaises(TxError):
            self.h.send(self.alice, T.SEND_LETTER, sealed_payload(self.alice, self.bob, b"x", 3), fee=self.h.chain.state.letter_fee())
        before_upgrade(self.h)
        lid = self.h.send(self.alice, T.SEND_LETTER, sealed_payload(self.alice, self.bob, b"old app", 1), fee=self.h.chain.state.letter_fee())
        lid2 = self.h.send(self.alice, T.SEND_LETTER, sealed_payload(self.alice, self.bob, b"new app", 2), fee=self.h.chain.state.letter_fee())
        self.h.mine()
        self.assertEqual(self.h.chain.state.letters[lid]["seal"], 1)
        self.assertEqual(self.h.chain.state.letters[lid2]["seal"], 2)
        # the client reads each with the seal the chain recorded
        self.assertEqual(self.node.read_letter(self.bob, lid), b"old app")
        self.assertEqual(self.node.read_letter(self.bob, lid2), b"new app")

    def test_client_seals_v1_before_activation_so_older_apps_can_read(self):
        before_upgrade(self.h)
        self.assertFalse(self.node.sealed_post_active())
        lid = self.node.send_letter(self.alice, self.bob.address, b"plain v1")
        self.assertEqual(self.node.submitted[-1]["payload"]["seal"], 1)
        self.h.mine()
        self.assertEqual(crypto.decrypt_packet(crypto.unwrap_from_sender(self.bob.enc_priv, self.h.chain.state.letters[lid]["wrapped_key"]),
                                               bytes.fromhex(self.h.chain.get_ciphertext(lid))), b"plain v1")


class ServiceGrantTests(unittest.TestCase):
    def test_service_2_comes_from_the_registrars_after_activation(self):
        h = Harness(founders=False)
        a = newcomers(h, 1)[0]
        pals = newcomers(h, 100)
        for i in range(0, 100, 20):
            correspond(h, a, pals[i:i + 20])
        with self.assertRaises(TxError) as cm:
            claim_grant(h, a, "service-2")
        self.assertIn("registrars", str(cm.exception))
        before = h.chain.state.balance(a.address)
        h.multisig([h.architect], T.GRANT, {"to": a.address, "tier": "service-2", "note": "earned"})
        h.mine()
        self.assertEqual(h.chain.state.balance(a.address), before + B(50))
        h.chain.state.check_invariant()
        # the registrars' list shows who is waiting, and drops them once granted
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        node = FakeNode(h.chain, headers_path=os.path.join(tmp.name, "h.json"))
        self.assertEqual(node.grant_candidates("service-2"), [])
        b = newcomers(h, 1)[0]
        for i in range(0, 100, 20):
            correspond(h, b, pals[i:i + 20])
        self.assertEqual([r["address"] for r in node.grant_candidates("service-2")], [b.address])

    def test_service_1_self_claims_are_capped_per_window(self):
        h = Harness(founders=False)
        window = h.chain.profile["service_claim_window_blocks"]
        cap = h.chain.profile["service_claims_per_window"]
        claimants = newcomers(h, cap + 1)
        pals = newcomers(h, 10)
        for c in claimants:
            correspond(h, c, pals)
        for c in claimants[:cap]:
            claim_grant(h, c, "service-1")
        with self.assertRaises(TxError) as cm:
            claim_grant(h, claimants[cap], "service-1")
        self.assertIn(f"{cap} service grants", str(cm.exception))
        h.mine()
        for _ in range(window):
            h.mine()
        claim_grant(h, claimants[cap], "service-1")            # the window has rolled on
        h.mine()
        self.assertEqual(h.chain.state.grant_counts["service-1"], cap + 1)
        h.chain.state.check_invariant()

    def test_old_rules_before_activation(self):
        h = before_upgrade(Harness(founders=False))
        a = newcomers(h, 1)[0]
        with self.assertRaises(TxError) as cm:
            claim_grant(h, a, "service-2")
        self.assertIn("needs 100", str(cm.exception))          # not "registrars": self-claim still open


class ReserveTests(unittest.TestCase):
    def setUp(self):
        self.h = Harness(founders=1)
        self.keeper = self.h.founders[0]

    def test_anyone_pays_in_only_the_quorum_pays_out(self):
        h, k = self.h, self.keeper
        h.send(k, T.TRANSFER, {"to": RESERVE, "amount": B(100), "memo": "to the reserve"})
        h.mine()
        st = h.chain.state
        self.assertEqual(st.balance(RESERVE), B(100))
        self.assertEqual(h.chain.supply()["reserve"], B(100))
        # nothing single-signed can move it: the reserve has no key
        with self.assertRaises(TxError):
            h.send(k, T.SEND_LETTER, {"to": RESERVE}, fee=st.letter_fee())
        txid = h.multisig([h.architect], T.RESERVE_TRANSFER, {"to": k.address, "amount": B(40), "note": "float"})
        h.mine()
        self.assertEqual(st.balance(RESERVE), B(60))
        self.assertEqual(h.chain.get_tx(txid)["tx"]["fee"], 0)
        with self.assertRaises(TxError):                        # more than it holds
            h.multisig([h.architect], T.RESERVE_TRANSFER, {"to": k.address, "amount": B(61)})
        with self.assertRaises(TxError):                        # never to a protocol account
            h.multisig([h.architect], T.RESERVE_TRANSFER, {"to": params.TREASURY_ADDRESS, "amount": B(1)})
        with self.assertRaises(TxError):                        # a stranger's approval is not a quorum
            h.multisig([k], T.RESERVE_TRANSFER, {"to": k.address, "amount": B(1)})
        st.check_invariant()

    def test_reserve_waits_for_activation(self):
        h = before_upgrade(self.h)
        h.send(self.keeper, T.TRANSFER, {"to": RESERVE, "amount": B(5)})
        h.mine()
        with self.assertRaises(TxError) as cm:
            h.multisig([h.architect], T.RESERVE_TRANSFER, {"to": self.keeper.address, "amount": B(1)})
        self.assertIn("switches on", str(cm.exception))

    def test_client_and_cli_shape(self):
        h, k = self.h, self.keeper
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        node = FakeNode(h.chain, headers_path=os.path.join(tmp.name, "h.json"))
        node.transfer(k, RESERVE, B(3))
        h.mine()
        self.assertEqual(node.get("/registrars")["reserve_balance"], B(3))
        node.reserve_transfer([h.architect], k.address, B(2), note="back")
        h.mine()
        self.assertEqual(h.chain.state.balance(RESERVE), B(1))
        self.assertEqual(node.get("/params")["reserve"], RESERVE)


if __name__ == "__main__":
    unittest.main()
