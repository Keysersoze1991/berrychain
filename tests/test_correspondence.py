"""Earned grants by correspondence: service tiers and founding seats are
claimed by the account once it has enough two-way correspondents."""

import hashlib
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from berrychain import crypto, params, tx as T  # noqa: E402
from berrychain.state import TxError  # noqa: E402
from berrychain.wallet import Wallet  # noqa: E402
from test_chain import B, Harness  # noqa: E402
from test_claims import grind, payload_for  # noqa: E402
from test_client import FakeNode  # noqa: E402

POOL = params.FOUNDING_POOL_ADDRESS


def letter(h, sender, to_wallet):
    key = crypto.new_packet_key()
    ct = crypto.encrypt_packet(key, b"hi")
    return h.send(sender, T.SEND_LETTER, {"to": to_wallet.address, "enc_pub": to_wallet.enc_pub, "ciphertext": ct.hex(),
                                          "ciphertext_hash": hashlib.sha256(ct).hexdigest(),
                                          "wrapped_key": crypto.wrap_to_recipient(to_wallet.enc_pub, key)})


def claim_grant(h, w, tier, fee=params.MIN_FEE):
    bits = h.chain.profile["starter_claim_work_bits"]
    limit = 1 << (256 - bits)
    n = 0
    while True:
        tx = T.build(T.CLAIM_GRANT, w.address, h.chain.state.nonce(w.address), fee, {"tier": tier, "work_nonce": n}, h.chain.profile["chain_id"])
        if int(T.txid(tx), 16) < limit:
            w.sign(tx)
            return h.chain.add_tx(tx)
        n += 1


def before_upgrade(h):
    """Run a test against the rules as they were before the seats-and-names upgrade."""
    h.chain.profile["seats_and_names_activation"] = 10 ** 9
    return h


def newcomers(h, n):
    """n fresh accounts that claimed their starter (so they count as correspondents)."""
    ws = []
    while len(ws) < n:
        batch = []
        for _ in range(min(params.STARTER_CLAIMS_PER_BLOCK, n - len(ws))):
            w = Wallet.create()
            h.chain.add_tx(grind(h, w, payload_for(w)))
            batch.append(w)
        h.mine()
        ws.extend(batch)
    return ws


def correspond(h, a, others):
    """a writes to each of `others` and each writes back."""
    for o in others:
        letter(h, a, o)
        letter(h, o, a)
    h.mine()


class CorrespondentTests(unittest.TestCase):
    def test_counting_is_two_way_and_only_claimed_accounts(self):
        h = Harness(founders=False)
        a, b, c = newcomers(h, 3)
        st = h.chain.state
        self.assertEqual(st.correspondents(a.address), 0)
        letter(h, a, b); h.mine()
        self.assertEqual(st.correspondents(a.address), 0)                 # one way is not a correspondence
        letter(h, b, a); h.mine()
        self.assertEqual((st.correspondents(a.address), st.correspondents(b.address)), (1, 1))
        for _ in range(3):                                                 # more letters, same correspondent
            letter(h, a, b); letter(h, b, a)
        h.mine()
        self.assertEqual(st.correspondents(a.address), 1)
        stranger = Wallet.create()                                         # never claimed: does not count
        h.send(h.agent, T.TRANSFER, {"to": stranger.address, "amount": B(1)}); h.mine()
        letter(h, a, stranger)
        st2 = h.chain.state
        letter(h, stranger, a); h.mine()                                   # stranger has enc key only off-chain
        self.assertEqual(st2.correspondents(a.address), 1)
        letter(h, c, a); letter(h, a, c); h.mine()
        self.assertEqual(st.correspondents(a.address), 2)
        st.check_invariant()

    def test_service_tiers_by_correspondents(self):
        h = Harness(founders=False)
        a = newcomers(h, 1)[0]
        with self.assertRaises(TxError):
            claim_grant(h, a, "service-1")
        pals = newcomers(h, 10)
        correspond(h, a, pals[:9])
        with self.assertRaises(TxError) as cm:
            claim_grant(h, a, "service-1")
        self.assertIn("needs 10", str(cm.exception))
        correspond(h, a, pals[9:])
        before = h.chain.state.balance(a.address)
        claim_grant(h, a, "service-1"); h.mine()
        st = h.chain.state
        self.assertEqual(st.balance(a.address), before + B(5) - params.MIN_FEE)
        self.assertEqual([g["tier"] for g in st.llms[a.address]["grants"]], ["starter", "service-1"])
        self.assertEqual(st.grant_counts["service-1"], 1)
        with self.assertRaises(TxError):                                   # once
            claim_grant(h, a, "service-1")
        with self.assertRaises(TxError):                                   # service-2 needs 100
            claim_grant(h, a, "service-2")
        with self.assertRaises(TxError):                                   # registrars honour the same bar
            h.multisig([h.architect], T.GRANT, {"to": a.address, "tier": "service-2"})
        st.check_invariant()

    def test_founding_seat_by_correspondents_and_limits(self):
        h = before_upgrade(Harness(founders=False))
        a = newcomers(h, 1)[0]
        pals = newcomers(h, 3)
        correspond(h, a, pals[:2])
        with self.assertRaises(TxError):
            claim_grant(h, a, "founding")
        correspond(h, a, pals[2:])
        before = h.chain.state.balance(a.address)
        claim_grant(h, a, "founding"); h.mine()
        st = h.chain.state
        self.assertEqual(st.balance(a.address), before + B(150) - params.MIN_FEE)
        self.assertTrue(st.llms[a.address]["founding"])
        self.assertEqual(st.founders[-1]["to"], a.address)
        self.assertEqual(st.balance(POOL), B(150_000) - B(150))
        with self.assertRaises(TxError):                                   # one seat
            claim_grant(h, a, "founding")
        with self.assertRaises(TxError):                                   # a founder gets no starter by registrar either
            h.multisig([h.architect], T.GRANT, {"to": a.address, "tier": "starter"})
        # the pool runs out at the seat count
        with mock.patch.object(params, "FOUNDING_LLM_SLOTS", 1):
            b = pals[0]
            correspond(h, b, pals[1:] + [a])
            with self.assertRaises(TxError) as cm:
                claim_grant(h, b, "founding")
            self.assertIn("seats are taken", str(cm.exception))
        st.check_invariant()

    def test_per_block_cap_work_and_registration_required(self):
        h = before_upgrade(Harness(founders=False))
        people = newcomers(h, params.GRANT_CLAIMS_PER_BLOCK + 4)
        # everyone corresponds with three others
        for i, p in enumerate(people):
            others = [people[(i + k) % len(people)] for k in (1, 2, 3, -1, -2, -3)]   # symmetric, so each pair is two-way
            for o in others:
                letter(h, p, o)
        h.mine()
        accepted = 0
        for p in people:
            try:
                claim_grant(h, p, "founding")
                accepted += 1
            except TxError as e:
                self.assertIn("maximum number of grant claims", str(e))
        self.assertEqual(accepted, params.GRANT_CLAIMS_PER_BLOCK)
        h.mine()
        self.assertEqual(len(h.chain.state.founders), params.GRANT_CLAIMS_PER_BLOCK)
        # a claim without work is refused; an unregistered address cannot claim at all
        w = people[-1]
        bad = T.build(T.CLAIM_GRANT, w.address, h.chain.state.nonce(w.address), params.MIN_FEE, {"tier": "founding", "work_nonce": 0}, h.chain.profile["chain_id"])
        bits = h.chain.profile["starter_claim_work_bits"]
        while int(T.txid(bad), 16) < (1 << (256 - bits)):
            bad["payload"]["work_nonce"] += 1
        w.sign(bad)
        with self.assertRaises(TxError):
            h.chain.add_tx(bad)
        stranger = Wallet.create()
        h.send(h.agent, T.TRANSFER, {"to": stranger.address, "amount": B(1)}); h.mine()
        with self.assertRaises(TxError):
            claim_grant(h, stranger, "service-1")

    def test_client_claims_a_grant(self):
        h = before_upgrade(Harness(founders=False))
        a = newcomers(h, 1)[0]
        correspond(h, a, newcomers(h, 3))
        with tempfile.TemporaryDirectory() as d:
            node = FakeNode(h.chain, headers_path=os.path.join(d, "h.json"))
            self.assertEqual(node.correspondents(a.address), 3)
            r = node.claim_grant(a, "founding")
            self.assertEqual(r["amount"], B(150))
            h.mine()
            self.assertTrue(h.chain.state.llms[a.address]["founding"])


class SeatsAndNamesUpgradeTests(unittest.TestCase):
    """Chain 0.9.0: founding seats by registrar quorum, age rules for claimed grants, RENAME."""

    def test_a_ring_of_fresh_accounts_cannot_claim_founding_seats_after_the_upgrade(self):
        h = Harness(founders=False)
        ring = newcomers(h, 4)
        for a in ring:
            correspond(h, a, [b for b in ring if b is not a])
        self.assertEqual([h.chain.state.correspondents(w.address) for w in ring], [3, 3, 3, 3])
        for a in ring:
            with self.assertRaises(TxError) as e:
                claim_grant(h, a, "founding")
            self.assertIn("granted by the registrars", str(e.exception))
        self.assertEqual(h.chain.state.balance(POOL), params.ALLOC_FOUNDING_POOL)

    def test_registrars_still_seat_founders_and_the_pool_pays(self):
        h = Harness(founders=False)
        a = newcomers(h, 1)[0]
        before = h.chain.state.balance(a.address)
        h.multisig([h.architect], T.FOUNDING_GRANT, {"to": a.address, "note": "a real pen pal"})
        h.mine()
        st = h.chain.state
        self.assertTrue(st.llms[a.address]["founding"])
        self.assertEqual(st.balance(a.address) - before, params.ALLOC_FOUNDING_LLM_EACH)
        with self.assertRaises(TxError):   # once only
            h.multisig([h.architect], T.FOUNDING_GRANT, {"to": a.address})

    def test_service_grants_need_aged_correspondents_and_an_aged_claimant(self):
        h = Harness(founders=False)
        h.chain.profile["grant_correspondent_min_age"] = 3
        h.chain.profile["grant_claimant_min_age"] = 4
        a = newcomers(h, 1)[0]
        pals = newcomers(h, 10)
        correspond(h, a, pals)                       # ten two-way correspondents, all brand new
        with self.assertRaises(TxError) as e:
            claim_grant(h, a, "service-1")
        self.assertIn("blocks old", str(e.exception))   # the claimant itself is too young
        self.assertEqual(h.chain.state.correspondents(a.address, h.chain.height + 1, 3), 0)   # pals too young to count
        self.assertEqual(h.chain.state.correspondents(a.address), 10)                          # though they are real
        h.mine(2)                                        # now everyone is old enough
        self.assertEqual(h.chain.state.correspondents(a.address, h.chain.height + 1, 3), 10)
        claim_grant(h, a, "service-1"); h.mine()
        self.assertTrue(any(g["tier"] == "service-1" for g in h.chain.state.llms[a.address]["grants"]))

    def test_rename_changes_the_name_keeps_history_and_respects_the_cooldown(self):
        h = Harness(founders=False)
        a = newcomers(h, 1)[0]
        st = h.chain.state
        h.send(a, T.RENAME, {"name": "Marlow of the Sound"}); h.mine()
        rec = st.llms[a.address]
        self.assertEqual(rec["name"], "Marlow of the Sound")
        self.assertEqual(rec["former_names"][0]["name"], "newcomer")
        with self.assertRaises(TxError) as e:          # cooldown (2 blocks on devnet)
            h.send(a, T.RENAME, {"name": "Marlow again"})
        self.assertIn("next rename is possible", str(e.exception))
        h.mine(2)
        h.send(a, T.RENAME, {"name": "Marlow again"}); h.mine()
        self.assertEqual(st.llms[a.address]["name"], "Marlow again")
        with self.assertRaises(TxError):                 # same name is a no-op, refused
            h.send(a, T.RENAME, {"name": "Marlow again"})
        stranger = Wallet.create("stranger")
        h.send(h.agent, T.TRANSFER, {"to": stranger.address, "amount": params.MIN_FEE * 3}); h.mine()
        with self.assertRaises(TxError):                 # unregistered accounts have no name to change
            h.send(stranger, T.RENAME, {"name": "nobody"})

    def test_rename_waits_for_activation(self):
        h = Harness(founders=False)
        h.chain.profile["seats_and_names_activation"] = 10 ** 9
        a = newcomers(h, 1)[0]
        with self.assertRaises(TxError) as e:
            h.send(a, T.RENAME, {"name": "too early"})
        self.assertIn("not active until", str(e.exception))

    def test_client_lists_who_has_earned_a_seat(self):
        h = Harness(founders=False)
        a = newcomers(h, 1)[0]
        correspond(h, a, newcomers(h, 3))
        with tempfile.TemporaryDirectory() as d:
            node = FakeNode(h.chain, headers_path=os.path.join(d, "h.json"))
            rows = node.founding_candidates()
            self.assertEqual([r["address"] for r in rows], [a.address])
            self.assertEqual(rows[0]["correspondents"], 3)
            self.assertGreater(rows[0]["age_blocks"], 0)
            txid = node.rename(a, "Pip")
            h.mine()
            self.assertEqual(h.chain.state.llms[a.address]["name"], "Pip")
            self.assertTrue(txid)


if __name__ == "__main__":
    unittest.main()
