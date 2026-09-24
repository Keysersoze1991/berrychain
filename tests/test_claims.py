"""Self-service starter claims: a brand-new wallet registers and collects the
starter grant in one transaction, paying the fee out of the grant."""

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from berrychain import params, tx as T  # noqa: E402
from berrychain.client import ClientError  # noqa: E402
from berrychain.state import TxError  # noqa: E402
from berrychain.wallet import Wallet  # noqa: E402
from test_chain import B, Harness  # noqa: E402
from test_client import FakeNode  # noqa: E402


def grind(h, wallet, payload, fee=params.MIN_FEE, want_valid=True):
    """Build a CLAIM_STARTER tx and choose work_nonce so the txid does (or does not) carry the work."""
    bits = h.chain.profile["starter_claim_work_bits"]
    limit = 1 << (256 - bits)
    n = 0
    while True:
        p = dict(payload, work_nonce=n)
        tx = T.build(T.CLAIM_STARTER, wallet.address, h.chain.state.nonce(wallet.address), fee, p, h.chain.profile["chain_id"])
        ok = int(T.txid(tx), 16) < limit
        if ok == want_valid:
            wallet.sign(tx)
            return tx
        n += 1


def payload_for(w, name="newcomer", kind="person"):
    return {"name": name, "kind": kind, "enc_pub": w.enc_pub}


class ClaimRulesTests(unittest.TestCase):
    def test_new_wallet_registers_and_is_paid_fee_from_grant(self):
        h = Harness(founders=False)
        w = Wallet.create("phone")
        self.assertEqual(h.chain.state.balance(w.address), 0)
        tx = grind(h, w, payload_for(w))
        h.chain.add_tx(tx)
        h.mine()
        st = h.chain.state
        starter = params.GRANT_TIERS["starter"]["amount"]
        self.assertEqual(st.balance(w.address), starter - params.MIN_FEE)
        rec = st.llms[w.address]
        self.assertEqual((rec["kind"], rec["name"], rec["founding"]), ("person", "newcomer", False))
        self.assertEqual(rec["grants"], [{"tier": "starter", "amount": starter, "height": h.chain.height, "claimed": True}])
        self.assertEqual(st.grant_counts["starter"], 1)
        self.assertTrue(st.grants[-1]["claimed"])
        st.check_invariant()

    def test_once_per_wallet_and_no_second_starter_by_registrar(self):
        h = Harness(founders=False)
        w = Wallet.create("phone")
        h.chain.add_tx(grind(h, w, payload_for(w)))
        h.mine()
        with self.assertRaises(TxError):
            h.chain.add_tx(grind(h, w, payload_for(w, "again")))
        with self.assertRaises(TxError):
            h.multisig([h.architect], T.GRANT, {"to": w.address, "tier": "starter"})
        registered = h.fund_and_register("funded")                          # a registered wallet cannot claim either
        with self.assertRaises(TxError):
            h.chain.add_tx(grind(h, registered, payload_for(registered)))

    def test_work_is_required(self):
        h = Harness(founders=False)
        w = Wallet.create("lazy")
        with self.assertRaises(TxError) as cm:
            h.chain.add_tx(grind(h, w, payload_for(w), want_valid=False))
        self.assertIn("bits of work", str(cm.exception))
        with mock.patch.dict(h.chain.profile, {"starter_claim_work_bits": 0}):    # a profile without work accepts any nonce
            tx = T.build(T.CLAIM_STARTER, w.address, 0, params.MIN_FEE, dict(payload_for(w), work_nonce=12345), h.chain.profile["chain_id"])
            h.chain.add_tx(w.sign(tx))

    def test_per_block_cap(self):
        h = Harness(founders=False)
        wallets = [Wallet.create(f"p{i}") for i in range(params.STARTER_CLAIMS_PER_BLOCK + 2)]
        accepted = 0
        for w in wallets:
            try:
                h.chain.add_tx(grind(h, w, payload_for(w)))
                accepted += 1
            except TxError as e:
                self.assertIn("maximum number of starter claims", str(e))
        self.assertEqual(accepted, params.STARTER_CLAIMS_PER_BLOCK)
        h.mine()
        self.assertEqual(sum(1 for r in h.chain.state.llms.values() if r.get("kind") == "person"), params.STARTER_CLAIMS_PER_BLOCK)
        h.chain.add_tx(grind(h, wallets[-1], payload_for(wallets[-1])))    # the next block takes more
        h.mine()
        self.assertIn(wallets[-1].address, h.chain.state.llms)
        h.chain.state.check_invariant()

    def test_claims_drive_the_halving_and_bad_kind_refused(self):
        h = Harness(founders=False)
        st = h.chain.state
        with mock.patch.object(params, "GRANT_HALVING_EVERY", 2):
            first = st.grant_amount("starter", 1)
            for i in range(2):
                w = Wallet.create(f"c{i}")
                h.chain.add_tx(grind(h, w, payload_for(w)))
            h.mine()
            self.assertEqual(st.grant_amount("starter", h.chain.height + 1), first // 2)
        w = Wallet.create("odd")
        with self.assertRaises(TxError):
            h.chain.add_tx(grind(h, w, payload_for(w, kind="robot")))

    def test_grant_smaller_than_fee_is_refused(self):
        h = Harness(founders=False)
        w = Wallet.create("late")
        with mock.patch.dict(params.GRANT_TIERS["starter"], {"amount": params.MIN_FEE - 1}):   # as if deep into the halvings
            self.assertEqual(h.chain.state.grant_amount("starter", 1), params.MIN_FEE - 1)
            with self.assertRaises(TxError) as cm:
                h.chain.add_tx(grind(h, w, payload_for(w)))
            self.assertIn("no longer covers the fee", str(cm.exception))


class ClaimClientTests(unittest.TestCase):
    def test_client_grinds_signs_and_wallet_is_funded(self):
        h = Harness(founders=False)
        w = Wallet.create("phone")
        with tempfile.TemporaryDirectory() as d:
            node = FakeNode(h.chain, headers_path=os.path.join(d, "h.json"))
            seen = []
            r = node.claim_starter(w, "Keyser", kind="person", progress=seen.append)
            self.assertEqual(r["work_bits"], h.chain.profile["starter_claim_work_bits"])
            self.assertEqual(r["amount"], params.GRANT_TIERS["starter"]["amount"])
            h.mine()
            self.assertEqual(h.chain.state.balance(w.address), r["amount"] - params.MIN_FEE)
            self.assertEqual(h.chain.state.llms[w.address]["kind"], "person")
            with self.assertRaises(ClientError):
                node.claim_starter(w, "Keyser again")
            # letters work straight away: the claim published the receiving key
            other = h.fund_and_register("friend")
            lid = node.send_letter(other, w.address, b"welcome aboard")
            h.mine()
            self.assertEqual(node.read_letter(w, lid), b"welcome aboard")


if __name__ == "__main__":
    unittest.main()
