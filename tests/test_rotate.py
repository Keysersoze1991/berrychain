"""Rotating receiving keys: a registered account publishes a fresh X25519 key;
letters to the old key are accepted for a grace window; the new key's private
half rides in the rotation as a backup wrapped to the root key, so the recovery
words restore it, unless the owner chose to let it burn."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from berrychain import crypto, params, tx as T  # noqa: E402
from berrychain.client import ClientError, compose_letter, open_letter  # noqa: E402
from berrychain.node import key_history  # noqa: E402
from berrychain.state import TxError  # noqa: E402
from berrychain.wallet import Wallet  # noqa: E402
from test_chain import Harness  # noqa: E402
from test_client import FakeNode  # noqa: E402


class RotateTests(unittest.TestCase):
    def setUp(self):
        self.h = Harness(founders=3)
        self.alice, self.bob, self.carol = self.h.founders
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.node = FakeNode(self.h.chain, headers_path=os.path.join(self.tmp.name, "h.json"))

    def rotate(self, w, backup=True):
        new_priv, new_pub = crypto.generate_encryption_keypair()
        payload = {"enc_pub": new_pub, "backup": crypto.wrap_to_recipient(w.root_enc_pub, bytes.fromhex(new_priv)) if backup else None}
        self.h.send(w, T.ROTATE_KEY, payload)
        self.h.mine()
        return new_priv, new_pub

    def test_rotation_changes_the_registered_key_and_keeps_history(self):
        st = self.h.chain.state
        first = st.llms[self.bob.address]["enc_pub"]
        _, new_pub = self.rotate(self.bob)
        rec = st.llms[self.bob.address]
        self.assertEqual(rec["enc_pub"], new_pub)
        self.assertEqual(rec["prev_enc_pub"], first)
        self.assertEqual(rec["registration_enc_pub"], first)
        hist = key_history(rec)
        self.assertEqual([k["enc_pub"] for k in hist["keys"]], [first, new_pub])
        self.assertTrue(hist["keys"][0]["root"])
        self.assertIsNotNone(hist["keys"][1]["backup"])
        self.assertEqual(hist["current"], new_pub)
        # the same key cannot be published twice, and unregistered accounts cannot rotate
        with self.assertRaises(TxError):
            self.h.chain.state.copy().apply_tx(self._rotate_tx(self.bob, new_pub), self.h.chain.height + 1)
        stranger = Wallet.create("x")
        self.h.send(self.alice, T.TRANSFER, {"to": stranger.address, "amount": params.berry(1)})
        self.h.mine()
        with self.assertRaises(TxError):
            self.h.chain.state.copy().apply_tx(self._rotate_tx(stranger, crypto.generate_encryption_keypair()[1]), self.h.chain.height + 1)

    def _rotate_tx(self, w, pub, backup=None):
        tx = T.build(T.ROTATE_KEY, w.address, self.h.chain.state.nonce(w.address), params.MIN_FEE, {"enc_pub": pub, "backup": backup}, self.h.chain.profile["chain_id"])
        w.sign(tx)
        return tx

    def test_letters_follow_the_current_key_with_a_grace_window(self):
        old_pub = self.bob.enc_pub
        new_priv, new_pub = self.rotate(self.bob)
        # a letter to the old key still lands inside the grace window
        self.h.send(self.alice, T.SEND_LETTER, self._letter_payload(self.bob.address, old_pub, b"old key, in time"), fee=self.h.chain.state.letter_fee())
        self.h.mine()
        # a letter to the new key lands
        self.h.send(self.alice, T.SEND_LETTER, self._letter_payload(self.bob.address, new_pub, b"new key"), fee=self.h.chain.state.letter_fee())
        self.h.mine()
        # a letter to a key that was never theirs is refused
        with self.assertRaises(TxError):
            self.h.chain.state.copy().apply_tx(self._signed(self.alice, T.SEND_LETTER, self._letter_payload(self.bob.address, crypto.generate_encryption_keypair()[1], b"?"), self.h.chain.state.letter_fee()), self.h.chain.height + 1)
        # after the grace window the old key is refused too
        for _ in range(params.KEY_GRACE_BLOCKS + 1):
            self.h.mine()
        with self.assertRaises(TxError):
            self.h.chain.state.copy().apply_tx(self._signed(self.alice, T.SEND_LETTER, self._letter_payload(self.bob.address, old_pub, b"late"), self.h.chain.state.letter_fee()), self.h.chain.height + 1)
        # the recipient opens each with the matching private key
        self.bob.add_key(new_priv, new_pub)
        bodies = sorted(open_letter(self.node.read_letter(self.bob, l["id"]))["body"] for l in self.node.inbox(self.bob))
        self.assertEqual(bodies, ["new key", "old key, in time"])

    def _signed(self, w, t, payload, fee):
        tx = T.build(t, w.address, self.h.chain.state.nonce(w.address), fee, payload, self.h.chain.profile["chain_id"])
        w.sign(tx)
        return tx

    def _letter_payload(self, to, enc_pub, body):
        key = crypto.new_packet_key()
        aad = crypto.letter_aad(self.alice.address, to)              # seal v2 (chain 0.10.0); alice is always the sender here
        ct = crypto.encrypt_packet(key, compose_letter(body.decode()), aad)
        import hashlib
        return {"to": to, "enc_pub": enc_pub, "ciphertext": ct.hex(), "ciphertext_hash": hashlib.sha256(ct).hexdigest(),
                "wrapped_key": crypto.wrap_to_recipient(enc_pub, key, aad), "amount": 0, "seal": 2}

    def test_client_rotates_and_the_words_restore_backed_up_keys_but_not_burned_ones(self):
        w = Wallet.create("dana", phrase="new")
        self.h.send(self.alice, T.TRANSFER, {"to": w.address, "amount": params.berry(2)})
        self.h.mine()
        self.h.send(w, T.REGISTER_LLM, {"name": "dana", "enc_pub": w.enc_pub})
        self.h.mine()
        root_pub = w.enc_pub
        # first rotation with a backup, second without
        self.node.rotate_key(w, backup=True)
        self.h.mine()
        kept_pub = w.enc_pub
        self.node.rotate_key(w, backup=False)
        self.h.mine()
        burned_pub = w.enc_pub
        self.assertEqual(len(w.enc_keys), 3)
        # letters to each key
        for pub, text in ((root_pub, "to root"), (kept_pub, "to kept"), (burned_pub, "to burned")):
            if pub == root_pub:
                continue  # root is two rotations back: past the grace window is fine to skip here
            self.node.send_letter(self.alice, w.address, compose_letter(text), enc_pub=pub)
            self.h.mine()
        # a fresh wallet from the words knows only the root key...
        r = Wallet.create("dana again", phrase=w.mnemonic)
        self.assertEqual(r.enc_pub, root_pub)
        self.assertEqual(r.address, w.address)
        # ...until it recovers the backups from the chain
        restored, missing = self.node.recover_keys(r)
        self.assertEqual(restored, [kept_pub])
        self.assertEqual(missing, [burned_pub])
        # the published current key was never backed up, so the recovered wallet
        # cannot receive on it: it stays on the root key and must rotate again
        self.assertEqual(r.enc_pub, root_pub)
        self.assertFalse(self.node.holds_current_key(r))
        self.node.rotate_key(r)
        self.h.mine()
        self.assertTrue(self.node.holds_current_key(r))
        bodies = {}
        for l in self.node.inbox(r):
            try:
                bodies[l["enc_pub"]] = open_letter(self.node.read_letter(r, l["id"]))["body"]
            except ClientError as e:
                bodies[l["enc_pub"]] = f"ERR {e}"
        self.assertEqual(bodies[kept_pub], "to kept")
        self.assertIn("no longer holds", bodies[burned_pub])
        # the original wallet, which still has the burned key, reads everything
        self.assertEqual(sorted(open_letter(self.node.read_letter(w, l["id"]))["body"] for l in self.node.inbox(w)), ["to burned", "to kept"])
        # saving and loading keeps every key
        path = os.path.join(self.tmp.name, "dana.json")
        w.save(path)
        again = Wallet.load(path)
        self.assertEqual(again.enc_keys, w.enc_keys)
        self.assertEqual(again.root_enc_pub, root_pub)

    def test_rotation_waits_for_activation(self):
        self.h.chain.profile["rotate_key_activation"] = self.h.chain.height + 5
        try:
            with self.assertRaises(TxError):
                self.h.chain.state.copy().apply_tx(self._rotate_tx(self.bob, crypto.generate_encryption_keypair()[1]), self.h.chain.height + 1)
            for _ in range(5):
                self.h.mine()
            self.rotate(self.bob)   # now fine
        finally:
            self.h.chain.profile["rotate_key_activation"] = 0


if __name__ == "__main__":
    unittest.main()
