import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from berrychain import crypto, push  # noqa: E402


def signed(action, priv, pub, token="ab" * 32, platform="ios", ts=None):
    address = crypto.address_from_pubkey(pub)
    ts = int(time.time()) if ts is None else ts
    sig = crypto.sign(priv, push.register_message(action, address, platform, token, ts))
    return {"action": action, "address": address, "pub": pub, "token": token, "platform": platform, "ts": ts, "sig": sig}


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.priv, self.pub = crypto.generate_signing_keypair()

    def test_a_good_registration_passes(self):
        body = signed("register", self.priv, self.pub, token="AB" * 32)
        self.assertEqual(push.check_registration(body), (crypto.address_from_pubkey(self.pub), "ios", "ab" * 32))

    def test_wrong_key_stale_time_and_bad_token_are_refused(self):
        other_priv, _ = crypto.generate_signing_keypair()
        body = signed("register", other_priv, self.pub)
        self.assertEqual(push.check_registration(body), "bad signature")
        body = signed("register", self.priv, self.pub, ts=int(time.time()) - 3600)
        self.assertEqual(push.check_registration(body), "timestamp too far from now")
        body = signed("register", self.priv, self.pub, token="not hex!")
        self.assertEqual(push.check_registration(body), "token must be hex")
        body = signed("register", self.priv, self.pub)
        body["address"] = "brry1" + "0" * 48
        self.assertEqual(push.check_registration(body), "pub does not match address")
        body = signed("register", self.priv, self.pub, platform="android")
        self.assertEqual(push.check_registration(body), "unsupported platform")


class RelayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.reg = push.Registry(os.path.join(self.tmp.name, "push", "reg.json"))
        self.me = "brry1" + "a" * 48
        self.other = "brry1" + "b" * 48
        self.blocks = {}
        self.tip = 10
        self.sent = []
        self.answer = (200, "")

        def fetch(path):
            if path == "/status":
                return {"height": self.tip}
            h = int(path.rsplit("/", 1)[1])
            return self.blocks.get(h, {"height": h, "txs": []})

        def sender(token, title, body):
            self.sent.append((token, title))
            return self.answer

        self.relay = push.Relay(self.reg, fetch, sender)

    def tearDown(self):
        self.tmp.cleanup()

    def letter(self, to, frm="brry1" + "c" * 48):
        return {"type": "SEND_LETTER", "from": frm, "payload": {"to": to, "ciphertext": "…"}}

    def test_first_tick_only_takes_the_tip(self):
        self.assertEqual(self.relay.tick(), 0)
        self.assertEqual(self.relay.height, 10)

    def test_a_letter_to_a_registered_address_is_pushed_once_with_a_count(self):
        self.relay.tick()
        self.reg.add("ab" * 32, self.me, "ios", 10)
        self.blocks[11] = {"height": 11, "txs": [self.letter(self.me), self.letter(self.me), self.letter(self.other), self.letter(self.me, frm=self.me)]}
        self.tip = 11
        self.assertEqual(self.relay.tick(), 1)
        self.assertEqual(self.sent, [("ab" * 32, "2 letters have arrived")])
        self.assertEqual(self.relay.tick(), 0)  # nothing new, nothing sent
        self.assertEqual(len(self.sent), 1)

    def test_dead_tokens_are_forgotten_and_the_file_persists(self):
        self.relay.tick()
        self.reg.add("ab" * 32, self.me, "ios", 10)
        self.reg.add("cd" * 32, self.me, "ios", 10)
        self.answer = (410, "Unregistered")
        self.blocks[11] = {"height": 11, "txs": [self.letter(self.me)]}
        self.tip = 11
        self.relay.tick()
        self.assertEqual(len(self.reg), 0)
        self.assertEqual(self.relay.dropped, 2)
        again = push.Registry(self.reg.path)
        self.assertEqual(len(again), 0)
        again.add("ef" * 32, self.other, "ios", 11)
        self.assertEqual(push.Registry(self.reg.path).for_address(self.other), ["ef" * 32])

    def test_http_register_and_unregister(self):
        import threading
        import urllib.request
        from http.server import ThreadingHTTPServer
        self.relay.tick()
        srv = ThreadingHTTPServer(("127.0.0.1", 0), push.make_handler(self.reg, self.relay, apns_ready=False))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        priv, pub = crypto.generate_signing_keypair()

        def post(path, body):
            req = urllib.request.Request(base + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req) as r:
                    return r.status, json.load(r)
            except urllib.error.HTTPError as e:
                return e.code, json.load(e)

        status, j = post("/push/register", signed("register", priv, pub))
        self.assertEqual((status, j["ok"], j["watching_from"]), (200, True, 10))
        self.assertEqual(self.reg.for_address(crypto.address_from_pubkey(pub)), ["ab" * 32])
        status, j = post("/push/register", signed("unregister", priv, pub))  # wrong action for the path
        self.assertEqual(status, 400)
        status, j = post("/push/unregister", signed("unregister", priv, pub))
        self.assertEqual((status, len(self.reg)), (200, 0))
        with urllib.request.urlopen(base + "/push/status") as r:
            self.assertEqual(json.load(r)["apns"], False)
        srv.shutdown()


class ApnsJwtTests(unittest.TestCase):
    def test_jwt_is_es256_and_cached(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        key = ec.generate_private_key(ec.SECP256R1())
        pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        a = push.Apns(pem, "KEYID12345", "TEAMID1234", "link.berrychain.wallet")
        t = a.jwt()
        header, claims, sig = t.split(".")
        pad = lambda s: s + "=" * (-len(s) % 4)  # noqa: E731
        import base64
        self.assertEqual(json.loads(base64.urlsafe_b64decode(pad(header))), {"alg": "ES256", "kid": "KEYID12345"})
        self.assertEqual(json.loads(base64.urlsafe_b64decode(pad(claims)))["iss"], "TEAMID1234")
        self.assertEqual(len(base64.urlsafe_b64decode(pad(sig))), 64)
        self.assertIs(a.jwt(), t)


if __name__ == "__main__":
    unittest.main()
