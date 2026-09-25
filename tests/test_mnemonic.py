"""Recovery phrases: BIP-39 encoding against the published vector, and a
wallet rebuilt from its words on another machine has the same keys."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from berrychain import mnemonic as M  # noqa: E402
from berrychain.wallet import Wallet  # noqa: E402

ZERO_PHRASE = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
ZERO_SEED = ("5eb00bbddcf069084889a8ab9155568165f5c453ccb85e70811aaed6f6da5fc1"
             "9a5ac40b389cd370d086206dec8aa6c43daea6690f20ad3d8d48b2d2ce9e38e4")


class MnemonicTests(unittest.TestCase):
    def test_bip39_vector(self):
        self.assertEqual(M.new_phrase(bytes(16)), ZERO_PHRASE)
        self.assertEqual(M.seed_from_phrase(ZERO_PHRASE).hex(), ZERO_SEED)
        self.assertEqual(len(M.wordlist()), 2048)

    def test_validation(self):
        p = M.new_phrase()
        self.assertEqual(len(p.split()), 12)
        self.assertEqual(M.validate("  " + p.upper() + " "), p)
        words = p.split()
        words[3] = "zoo" if words[3] != "zoo" else "zone"
        with self.assertRaises(ValueError):                     # checksum catches a swapped word (almost always)
            for _ in range(1):
                M.validate(" ".join(words))
        with self.assertRaises(ValueError):
            M.validate(" ".join(words[:11]))
        with self.assertRaises(ValueError):
            M.validate(p.replace(words[0], "notaword", 1))

    def test_wallet_from_phrase_round_trip(self):
        w = Wallet.create("phone", phrase="new")
        self.assertIsNotNone(w.mnemonic)
        again = Wallet.create("other phone", phrase=w.mnemonic)
        self.assertEqual((again.address, again.enc_pub, again.sign_priv), (w.address, w.enc_pub, w.sign_priv))
        # the phrase survives sealing and reloading
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "w.json")
            w.passphrase = "correct horse"
            w.save(path)
            back = Wallet.load(path, passphrase="correct horse")
            self.assertEqual(back.mnemonic, w.mnemonic)
            self.assertNotIn(w.mnemonic.split()[0], open(path).read())   # sealed, not plain
        # a random-key wallet has no phrase and says so
        self.assertIsNone(Wallet.create("legacy").mnemonic)

    def test_different_phrases_different_wallets(self):
        a, b = Wallet.create(phrase="new"), Wallet.create(phrase="new")
        self.assertNotEqual(a.address, b.address)


if __name__ == "__main__":
    unittest.main()
