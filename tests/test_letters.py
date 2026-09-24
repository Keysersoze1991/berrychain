"""Sealed letters: addressed, end-to-end encrypted messages carried by the
chain. Consensus rules at the state level, then the client round trip over
the fake node, then the plaintext envelope both CLI and MCP use."""

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


def seal(to_enc_pub: str, content: bytes, **extra) -> tuple[dict, bytes]:
    key = crypto.new_packet_key()
    ct = crypto.encrypt_packet(key, content)
    payload = {"ciphertext": ct.hex(), "ciphertext_hash": hashlib.sha256(ct).hexdigest(),
               "wrapped_key": crypto.wrap_to_recipient(to_enc_pub, key), **extra}
    return payload, key


class LetterRulesTests(unittest.TestCase):
    def test_registered_recipient_reads_and_nobody_else_can(self):
        h = Harness(founders=3)
        alice, bob, eve = h.founders
        payload, _ = seal(bob.enc_pub, b"meet at the lighthouse", to=bob.address)
        lid = h.send(alice, T.SEND_LETTER, payload)
        h.mine()
        l = h.chain.state.letters[lid]
        self.assertEqual((l["from"], l["to"], l["amount"], l["enc_pub"]), (alice.address, bob.address, 0, bob.enc_pub))
        self.assertNotIn("ciphertext", l)                                  # bulk bytes stay in the block
        key = crypto.unwrap_from_sender(bob.enc_priv, l["wrapped_key"])
        self.assertEqual(crypto.decrypt_packet(key, bytes.fromhex(h.chain.get_ciphertext(lid))), b"meet at the lighthouse")
        with self.assertRaises(Exception):
            crypto.unwrap_from_sender(eve.enc_priv, l["wrapped_key"])
        with self.assertRaises(Exception):
            crypto.unwrap_from_sender(alice.enc_priv, l["wrapped_key"])     # the sender only keeps the key off-chain
        self.assertEqual(h.chain.state.balance(alice.address), B(1_000) - params.MIN_FEE)
        h.chain.state.check_invariant()

    def test_amount_rides_with_the_letter(self):
        h = Harness(founders=2)
        alice, bob = h.founders
        payload, _ = seal(bob.enc_pub, b"for the ferry", to=bob.address, amount=B(2))
        h.send(alice, T.SEND_LETTER, payload)
        h.mine()
        self.assertEqual(h.chain.state.balance(bob.address), B(1_002))
        self.assertEqual(h.chain.state.balance(alice.address), B(998) - params.MIN_FEE)
        h.chain.state.check_invariant()

    def test_unregistered_recipient_needs_a_supplied_key(self):
        h = Harness(founders=1)
        alice = h.founders[0]
        carol = Wallet.create("carol")                                     # never registered
        payload, _ = seal(carol.enc_pub, b"hi", to=carol.address)
        with self.assertRaises(TxError):
            h.send(alice, T.SEND_LETTER, payload)
        payload["enc_pub"] = carol.enc_pub
        lid = h.send(alice, T.SEND_LETTER, payload)
        h.mine()
        key = crypto.unwrap_from_sender(carol.enc_priv, h.chain.state.letters[lid]["wrapped_key"])
        self.assertEqual(crypto.decrypt_packet(key, bytes.fromhex(h.chain.get_ciphertext(lid))), b"hi")

    def test_registered_key_wins_over_a_supplied_one(self):
        h = Harness(founders=3)
        alice, bob, eve = h.founders
        payload, _ = seal(eve.enc_pub, b"redirected", to=bob.address, enc_pub=eve.enc_pub)
        with self.assertRaises(TxError):                                   # a lie about bob's key is refused
            h.send(alice, T.SEND_LETTER, payload)

    def test_malformed_letters_are_refused(self):
        h = Harness(founders=2)
        alice, bob = h.founders
        good, _ = seal(bob.enc_pub, b"x", to=bob.address)
        bad = [
            dict(good, ciphertext_hash="00" * 32),
            dict(good, ciphertext=""),
            dict(good, wrapped_key={"epk": "00", "nonce": "00", "ct": "00"}),
            dict(good, to=params.TREASURY_ADDRESS),
            dict(good, amount=-1),
            dict(good, amount=B(5_000)),                                    # more than alice has
            dict(good, ciphertext="ff" * (params.MAX_PACKET_INLINE_BYTES + 1),
                 ciphertext_hash=hashlib.sha256(b"\xff" * (params.MAX_PACKET_INLINE_BYTES + 1)).hexdigest()),
        ]
        for p in bad:
            with self.assertRaises(TxError, msg=str(p)[:80]):
                h.send(alice, T.SEND_LETTER, p)
        self.assertEqual(h.chain.state.letters, {})
        h.send(alice, T.SEND_LETTER, good)
        h.mine()
        self.assertEqual(len(h.chain.state.letters), 1)


class LetterClientTests(unittest.TestCase):
    def setUp(self):
        self.h = Harness(founders=3)
        self.alice, self.bob, self.eve = self.h.founders
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.node = FakeNode(self.h.chain, headers_path=os.path.join(self.tmp.name, "headers.json"))

    def test_send_inbox_read_as_recipient_and_sender(self):
        content = compose_letter("Bring the charts.", subject="Tomorrow", sender_name="alice")
        lid = self.node.send_letter(self.alice, self.bob.address, content)
        self.h.mine()
        inbox = self.node.inbox(self.bob)
        self.assertEqual([l["id"] for l in inbox], [lid])
        self.assertEqual(self.node.inbox(self.eve), [])
        self.assertEqual([l["id"] for l in self.node.sent(self.alice)], [lid])
        env = open_letter(self.node.read_letter(self.bob, lid))
        self.assertEqual((env["subject"], env["body"], env["from_name"]), ("Tomorrow", "Bring the charts.", "alice"))
        self.assertEqual(open_letter(self.node.read_letter(self.alice, lid))["body"], "Bring the charts.")   # sender rereads
        with self.assertRaises(ClientError):
            self.node.read_letter(self.eve, lid)
        self.assertIn(lid, self.alice.packet_keys)
        self.assertEqual(self.node.inbox(self.bob, since=self.h.chain.height + 1), [])

    def test_unregistered_recipient_round_trip_and_amount(self):
        carol = Wallet.create("carol")
        with self.assertRaises(ClientError):
            self.node.send_letter(self.alice, carol.address, b"hello")
        lid = self.node.send_letter(self.alice, carol.address, b"hello", amount_seeds=B(1), enc_pub=carol.enc_pub)
        self.h.mine()
        self.assertEqual(self.node.read_letter(carol, lid), b"hello")
        self.assertEqual(self.h.chain.state.balance(carol.address), B(1))

    def test_tampered_ciphertext_is_detected(self):
        lid = self.node.send_letter(self.alice, self.bob.address, b"true words")
        self.h.mine()
        real = self.node.letter(lid)
        def liar(path, obj):
            if path.startswith("/letter/") and obj:
                return dict(obj, ciphertext="00" * 40)
            return obj
        liar_node = FakeNode(self.h.chain, liar, headers_path=os.path.join(self.tmp.name, "h2.json"))
        with self.assertRaises(ClientError):
            liar_node.read_letter(self.bob, lid)
        self.assertEqual(self.node.read_letter(self.bob, lid), b"true words")
        self.assertEqual(real["to"], self.bob.address)


class EnvelopeTests(unittest.TestCase):
    def test_round_trip_and_fallbacks(self):
        env = open_letter(compose_letter("body", subject="s", reply_to="abc", sender_name="n"))
        self.assertEqual(env, {"subject": "s", "body": "body", "reply_to": "abc", "from_name": "n"})
        self.assertEqual(open_letter(b"plain text")["body"], "plain text")
        self.assertEqual(open_letter(b"\xff\x00")["encoding"], "hex")


if __name__ == "__main__":
    unittest.main()
