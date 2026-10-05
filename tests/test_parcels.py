"""The parcel room: priced, sealed, hash-checked large attachments beside the chain."""
import hashlib
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from berrychain import crypto, params, parcels as P  # noqa: E402
from berrychain.client import ClientError, compose_letter, open_letter  # noqa: E402
from test_chain import Harness  # noqa: E402
from test_client import FakeNode  # noqa: E402

MB = 1024 * 1024
B = params.SEEDS_PER_BERRY


class PriceTests(unittest.TestCase):
    def test_one_berry_per_started_chunk(self):
        self.assertEqual(P.price_for(1), B)                      # defaults: 100 MB chunk, so one berry
        self.assertEqual(P.price_for(100 * MB), B)
        self.assertEqual(P.price_for(0), B)
        self.assertEqual(P.price_for(5 * MB, 5 * MB, B), B)       # a room with 5 MB chunks
        self.assertEqual(P.price_for(5 * MB + 1, 5 * MB, B), 2 * B)
        self.assertEqual(P.price_for(12 * MB, 5 * MB, B), 3 * B)


class RoomTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.room = P.Room(self.tmp.name, max_bytes=3 * MB, chunk=MB, per_chunk=B, ttl_days=1)
        self.data = os.urandom(1_500_000)
        self.h = hashlib.sha256(self.data).hexdigest()

    def tearDown(self):
        self.tmp.cleanup()

    def test_upload_waits_for_payment_then_serves(self):
        status, _ = self.room.store(self.h, self.data)
        self.assertEqual(status, 202)                      # stored, pending payment
        self.assertIsNone(self.room.fetch(self.h))         # not served until paid
        self.room.note_payment(self.h, "brry1payer", B, 10)
        self.assertIsNone(self.room.fetch(self.h))         # 1.5 MB needs 2 BERRY at 1 MB chunks
        self.room.note_payment(self.h, "brry1payer", B, 11)
        self.assertEqual(self.room.fetch(self.h), self.data)
        self.assertEqual(self.room.summary()["paid"], 1)

    def test_bad_hash_oversize_and_underpaid_are_refused(self):
        self.assertEqual(self.room.store("ab" * 32, self.data)[0], 400)
        self.assertEqual(self.room.store(self.h, os.urandom(3 * MB + 1))[0], 413)
        self.assertEqual(self.room.store("zz", self.data)[0], 400)
        self.room.note_payment(self.h, "brry1payer", B, 10)
        self.assertEqual(self.room.store(self.h, self.data)[0], 402)   # paid for 1 MB, sent 1.5

    def test_sweep_drops_unpaid_uploads_and_expired_parcels(self):
        self.room.store(self.h, self.data)
        self.assertEqual(self.room.sweep(now=time.time() + P.PENDING_SECONDS + 1), 1)
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "blobs", self.h)))
        self.room.note_payment(self.h, "brry1payer", 2 * B, 12)
        self.room.store(self.h, self.data)
        self.assertEqual(self.room.sweep(now=time.time() + 3600), 0)
        self.assertEqual(self.room.sweep(now=time.time() + 2 * 86400), 1)
        self.assertEqual(self.room.summary()["parcels"], 0)

    def test_index_survives_a_restart(self):
        self.room.note_payment(self.h, "brry1payer", 2 * B, 12)
        self.room.store(self.h, self.data)
        again = P.Room(self.tmp.name, max_bytes=3 * MB, chunk=MB, per_chunk=B, ttl_days=1)
        self.assertEqual(again.fetch(self.h), self.data)


class WatcherTests(unittest.TestCase):
    def test_payments_with_the_memo_are_noted_others_ignored(self):
        tmp = tempfile.TemporaryDirectory()
        room = P.Room(tmp.name, chunk=MB, per_chunk=B)
        addr = "brry1room"
        h = "cd" * 32
        blocks = {1: {"height": 1, "txs": [
            {"type": "TRANSFER", "from": "brry1alice", "payload": {"to": addr, "amount": 2 * B, "memo": P.memo_for(h)}},
            {"type": "TRANSFER", "from": "brry1bob", "payload": {"to": addr, "amount": B, "memo": "thanks"}},
            {"type": "TRANSFER", "from": "brry1bob", "payload": {"to": "brry1other", "amount": B, "memo": P.memo_for(h)}},
        ]}}
        tip = {"h": 0}

        def fetch(path):
            if path == "/status":
                return {"height": tip["h"]}
            lo = int(path.split("from=")[1].split("&")[0])
            return {"blocks": [blocks[i] for i in range(lo, tip["h"] + 1) if i in blocks]}

        w = P.Watcher(room, fetch, addr)
        self.assertEqual(w.tick(), 0)          # first tick just takes the tip
        tip["h"] = 1
        self.assertEqual(w.tick(), 1)
        self.assertEqual(room.index[h]["paid"], 2 * B)
        self.assertEqual(room.index[h]["payer"], "brry1alice")
        self.assertEqual(len(room.index), 1)
        tmp.cleanup()


class EndToEndTests(unittest.TestCase):
    """Alice seals a file, pays the room, uploads; the letter carries the key; Bob fetches and opens it."""

    def setUp(self):
        self.h = Harness()
        self.alice, self.bob = self.h.founders[:2]
        self.tmp = tempfile.TemporaryDirectory()
        self.node = FakeNode(self.h.chain, headers_path=os.path.join(self.tmp.name, "h.json"))
        self.room_addr = self.h.founders[5].address
        self.room = P.Room(os.path.join(self.tmp.name, "room"), max_bytes=2 * MB, chunk=MB, per_chunk=B)
        self.watcher = P.Watcher(self.room, self.node._route, self.room_addr)
        self.watcher.tick()
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), P.make_handler(self.room, self.watcher, self.room_addr))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def tearDown(self):
        self.srv.shutdown()
        self.tmp.cleanup()

    def test_send_fetch_and_delete(self):
        payload = os.urandom(1_200_000)
        before = self.h.chain.state.balance(self.alice.address)
        room_before = self.h.chain.state.balance(self.room_addr)
        ref = self.node.send_parcel(self.alice, payload, "holiday.zip", room=self.base)
        self.assertEqual(ref["price"], 2 * B)
        self.assertIn("waiting for a payment", ref["status"])
        self.h.mine()                                         # the payment lands
        self.watcher.tick()
        self.assertEqual(self.h.chain.state.balance(self.room_addr) - room_before, 2 * B)
        self.assertLess(self.h.chain.state.balance(self.alice.address), before - 2 * B)
        content = compose_letter("the photos from the trip", subject="Parcel", sender_name="alice", parcel=ref)
        lid = self.node.send_letter(self.alice, self.bob.address, content)
        self.h.mine()
        env = open_letter(self.node.read_letter(self.bob, lid))
        self.assertEqual(env["parcel"]["name"], "holiday.zip")
        self.assertEqual(env["parcel"]["size"], ref["size"])
        self.assertEqual(self.node.fetch_parcel(env["parcel"]), payload)
        self.assertEqual(self.room.summary()["served"], 1)
        # the room holds only ciphertext: the key is in the letter, not in the room
        with open(os.path.join(self.tmp.name, "room", "blobs", ref["hash"]), "rb") as f:
            self.assertNotIn(payload[:64], f.read())
        # a tampered room is caught by the hash
        tampered = dict(env["parcel"], hash="00" * 32)
        with self.assertRaises(ClientError):
            self.node.fetch_parcel(tampered)
        # only the payer may delete
        self.assertFalse(self.node.delete_parcel(self.bob, env["parcel"]))
        self.assertTrue(self.node.delete_parcel(self.alice, env["parcel"]))
        with self.assertRaises(ClientError):
            self.node.fetch_parcel(env["parcel"])

    def test_status_route(self):
        with urllib.request.urlopen(self.base + "/parcels/status") as r:
            st = json.load(r)
        self.assertEqual(st["address"], self.room_addr)
        self.assertEqual(st["price_per_chunk"], B)
        self.assertEqual(st["max_bytes"], 2 * MB)


if __name__ == "__main__":
    unittest.main()
