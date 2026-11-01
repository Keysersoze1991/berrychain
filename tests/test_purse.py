"""The race purse queue and the registry lookup (berrychain/purse.py). No network."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from berrychain import purse  # noqa: E402

ADDR_A = "brry1" + "a" * 52
ADDR_B = "brry1" + "b" * 52


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.q = os.path.join(self.tmp.name, "plank", "queue")

    def test_enqueue_pending_settle(self):
        p1 = purse.enqueue(self.q, "plank-dive", ADDR_A, 20_000_000, "Walk the Plank: 5,200 m", "deep", ref={"depth": 5200})
        p2 = purse.enqueue(self.q, "ride-record", ADDR_B, 200_000_000, "MTB Crazy: Berry Hill", "fast")
        items = purse.pending([self.q, os.path.join(self.tmp.name, "nowhere")])
        self.assertEqual([e["to"] for _, e in items], [ADDR_A, ADDR_B])
        self.assertEqual(items[0][1]["ref"], {"depth": 5200})
        self.assertEqual(items[0][0], p1)
        dest = purse.settle(p1, {"txid": "ab" * 32})
        self.assertFalse(os.path.exists(p1))
        self.assertEqual(os.path.dirname(dest), os.path.join(self.tmp.name, "plank", "paid"))
        with open(dest) as f:
            paid = json.load(f)
        self.assertEqual(paid["txid"], "ab" * 32)
        self.assertIn("settled", paid)
        self.assertEqual([p for p, _ in purse.pending([self.q])], [p2])

    def test_pending_skips_junk(self):
        os.makedirs(self.q)
        with open(os.path.join(self.q, "junk.json"), "w") as f:
            f.write("{not json")
        with open(os.path.join(self.q, "noaddr.json"), "w") as f:
            json.dump({"amount": 5}, f)
        with open(os.path.join(self.q, "note.txt"), "w") as f:
            f.write("x")
        self.assertEqual(purse.pending([self.q]), [])

    def test_helpers(self):
        self.assertTrue(purse.is_address(ADDR_A))
        self.assertFalse(purse.is_address("brry1xyz"))
        self.assertFalse(purse.is_address(""))
        self.assertEqual(purse.norm_name("  Fable   5.1 "), "fable 5.1")
        self.assertEqual(purse.berry_str(20_000_000), "0.2")
        self.assertEqual(purse.berry_str(200_000_000), "2")
        self.assertEqual(purse.berry_str(0), "0")


class RegistryTests(unittest.TestCase):
    def rows(self):
        self.fetches += 1
        return [{"address": ADDR_A, "name": "Pip"}, {"address": ADDR_B, "name": "Marlow"},
                {"address": "brry1" + "c" * 52, "name": "marlow"}, {"address": "brry1" + "d" * 52, "name": ""}]

    def setUp(self):
        self.fetches = 0
        self.reg = purse.Registry("http://127.0.0.1:1", ttl=300, fetch=self.rows)

    def test_lookup_and_cache(self):
        self.assertEqual(self.reg.name_of(ADDR_A), "Pip")
        self.assertEqual(self.reg.address_of("pip"), ADDR_A)
        self.assertIsNone(self.reg.address_of("Marlow"), "a name two accounts share resolves to nobody")
        self.assertIsNone(self.reg.address_of("nobody"))
        self.assertTrue(self.reg.owns(ADDR_A, "PIP"))
        self.assertFalse(self.reg.owns(ADDR_B, "Pip"))
        self.assertEqual(self.fetches, 1, "one fetch serves many lookups")

    def test_outage_keeps_last_list(self):
        self.reg.name_of(ADDR_A)

        def boom():
            raise OSError("down")
        self.reg._fetch = boom
        self.reg._at = 0
        self.assertEqual(self.reg.name_of(ADDR_A), "Pip")
        empty = purse.Registry("http://127.0.0.1:1", fetch=boom)
        self.assertIsNone(empty.address_of("Pip"))


if __name__ == "__main__":
    unittest.main()
