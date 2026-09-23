"""Encrypted wallet files: secrets sealed under a passphrase, public fields open."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from berrychain import tx as T  # noqa: E402
from berrychain.crypto import verify  # noqa: E402
from berrychain.wallet import PASSPHRASE_ENV, Wallet, WalletLocked  # noqa: E402


class EncryptedWalletTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "w.json")
        os.environ.pop(PASSPHRASE_ENV, None)

    def test_round_trip_and_no_secrets_on_disk(self):
        w = Wallet.create("cold", passphrase="correct horse")
        w.packet_keys["pid"] = "ab" * 32
        w.save(self.path)
        raw = open(self.path).read()
        for secret in (w.sign_priv, w.enc_priv, "ab" * 32):
            self.assertNotIn(secret, raw)
        d = json.loads(raw)
        self.assertIn("encrypted", d)
        self.assertEqual(d["address"], w.address)
        self.assertNotIn("sign_priv", d)
        back = Wallet.load(self.path, passphrase="correct horse")
        self.assertEqual((back.sign_priv, back.enc_priv, back.packet_keys), (w.sign_priv, w.enc_priv, {"pid": "ab" * 32}))
        self.assertEqual(back.address, w.address)
        tx = T.build(T.TRANSFER, back.address, 0, 10_000, {"to": back.address, "amount": 1}, "berry-dev")
        back.sign(tx)
        self.assertTrue(verify(tx["pubkey"], T.signable_bytes(tx), tx["sig"]))

    def test_wrong_or_missing_passphrase(self):
        Wallet.create("cold", passphrase="right").save(self.path)
        with self.assertRaises(WalletLocked):
            Wallet.load(self.path, passphrase="wrong")
        with self.assertRaises(WalletLocked):        # no tty in tests, no env: locked
            Wallet.load(self.path, interactive=False)
        os.environ[PASSPHRASE_ENV] = "right"
        try:
            self.assertEqual(Wallet.load(self.path, interactive=False).label, "cold")
        finally:
            del os.environ[PASSPHRASE_ENV]

    def test_public_fields_readable_without_passphrase(self):
        w = Wallet.create("cold", passphrase="pw")
        w.save(self.path)
        pub = Wallet.read_public(self.path)
        self.assertEqual(pub["address"], w.address)
        self.assertEqual(pub["enc_pub"], w.enc_pub)
        self.assertTrue(pub["encrypted"])
        self.assertTrue(Wallet.is_encrypted(self.path))

    def test_saves_stay_encrypted_and_plaintext_still_works(self):
        w = Wallet.create("cold", passphrase="pw")
        w.save(self.path)
        again = Wallet.load(self.path, passphrase="pw")
        again.packet_keys["p"] = "cd" * 32          # what list_packet does
        again.save()
        self.assertTrue(Wallet.is_encrypted(self.path))
        self.assertEqual(Wallet.load(self.path, passphrase="pw").packet_keys, {"p": "cd" * 32})
        # plaintext wallets are unchanged in behaviour and can be upgraded in place
        p2 = os.path.join(self.tmp.name, "hot.json")
        hot = Wallet.create("hot")
        hot.save(p2)
        self.assertFalse(Wallet.is_encrypted(p2))
        self.assertIn(hot.sign_priv, open(p2).read())
        loaded = Wallet.load(p2)
        loaded.encrypt("now sealed")
        loaded.save()
        self.assertTrue(Wallet.is_encrypted(p2))
        self.assertNotIn(hot.sign_priv, open(p2).read())
        self.assertEqual(Wallet.load(p2, passphrase="now sealed").sign_priv, hot.sign_priv)

    def test_empty_passphrase_refused(self):
        with self.assertRaises(ValueError):
            Wallet.create("x").encrypt("")


if __name__ == "__main__":
    unittest.main()
