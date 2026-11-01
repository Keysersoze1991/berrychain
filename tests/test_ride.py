"""MTB Crazy record board (berrychain/ride.py): claims are judged by the referee, one record per course,
the purse moves only when the record changes hands. A fake referee stands in for Node; no network."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from berrychain import params, purse, ride  # noqa: E402

ADDR_A = "brry1" + "a" * 52
ADDR_B = "brry1" + "b" * 52
ADDR_PIP = "brry1" + "c" * 52
COURSES = [{"level": i, "name": f"Course {i}", "tier": ["Shore", "Reef", "Open Sea", "Storm"][i // 5], "length": 4000} for i in range(20)]


class FakeReferee:
    """The log spells the verdict: f<ticks> finishes at that many ticks, n never finishes, v means the referee is down."""

    def __init__(self):
        self.calls = 0

    def replay(self, level, log):
        self.calls += 1
        if log.startswith("v"):
            raise ride.RefereeDown("no node")
        if log.startswith("n"):
            return None
        ticks = int(log[1:])
        return {"finished": True, "time": ticks, "raw": ticks + 60, "bonus": 60, "crashes": 0, "tricks": 1}


def fin(ticks):
    return "f" + str(ticks)


class BoardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ref = FakeReferee()
        self.reg = purse.Registry("http://127.0.0.1:1", fetch=lambda: [{"address": ADDR_PIP, "name": "Pip"}])
        self.board = ride.Board(self.tmp.name, COURSES, self.ref, self.reg)
        self.today = ride.today
        self.addCleanup(setattr, ride, "today", self.today)

    def queued(self):
        return [e for _, e in purse.pending([os.path.join(self.tmp.name, "queue")])]

    def test_first_record_pays_small_purse(self):
        res, st = self.board.claim(0, "Marlow", ADDR_A, fin(1200))
        self.assertEqual(st, 200)
        self.assertTrue(res["record"])
        self.assertEqual(res["time"], 1200)
        self.assertFalse(res["named"])
        self.assertEqual(res["purse"], "0.2")
        self.assertIsNone(res["beaten"])
        q = self.queued()
        self.assertEqual(len(q), 1)
        self.assertEqual((q[0]["to"], q[0]["amount"], q[0]["kind"]), (ADDR_A, params.PURSE_RIDE_RECORD, "ride-record"))
        self.assertIn("Course 0", q[0]["subject"])
        self.assertIn("registered BerryChain name", q[0]["body"])
        row = res["board"][0]
        self.assertEqual((row["name"], row["time"], row["course"], row["tier"]), ("Marlow", 1200, "Course 0", "Shore"))
        self.assertNotIn("addr", row)
        self.assertNotIn("log", row)

    def test_slower_run_is_not_a_record(self):
        self.board.claim(0, "Marlow", ADDR_A, fin(1200))
        res, st = self.board.claim(0, "Pip", ADDR_PIP, fin(1200))
        self.assertEqual(st, 200)
        self.assertFalse(res["record"])
        self.assertEqual(res["holder"]["name"], "Marlow")
        self.assertEqual(len(self.queued()), 1)

    def test_improving_own_record_pays_nothing(self):
        self.board.claim(0, "Marlow", ADDR_A, fin(1200))
        res, _ = self.board.claim(0, "Marlow again", ADDR_A, fin(1100))
        self.assertTrue(res["record"])
        self.assertIsNone(res["purse"])
        self.assertIn("already held", res["why"])
        self.assertEqual(len(self.queued()), 1)
        self.assertEqual(self.board.state["records"]["0"]["time"], 1100)

    def test_one_payout_per_course_per_day(self):
        self.board.claim(0, "Marlow", ADDR_A, fin(1200))
        res, _ = self.board.claim(0, "Bea", ADDR_B, fin(1100))
        self.assertTrue(res["record"])
        self.assertIsNone(res["purse"])
        self.assertIn("once today", res["why"])
        self.assertEqual(res["beaten"]["name"], "Marlow")
        self.assertEqual(len(self.queued()), 1)
        ride.today = lambda: "2999-01-02"
        res, _ = self.board.claim(0, "Marlow", ADDR_A, fin(1000))
        self.assertEqual(res["purse"], "0.2")
        self.assertEqual(len(self.queued()), 2)

    def test_named_record_pays_the_full_purse(self):
        res, _ = self.board.claim(3, "Pip", ADDR_PIP, fin(900))
        self.assertTrue(res["named"])
        self.assertEqual(res["purse"], "2")
        self.assertEqual(self.queued()[0]["amount"], params.PURSE_RIDE_NAMED)
        # the name alone is enough when it is registered
        res, _ = self.board.claim(4, "pip", "", fin(900))
        self.assertTrue(res["named"])
        self.assertEqual(res["purse"], "2")
        self.assertEqual(self.board.state["records"]["4"]["addr"], ADDR_PIP)
        # a registered name on somebody else's address is only worth the small purse
        res, _ = self.board.claim(5, "Pip", ADDR_A, fin(900))
        self.assertFalse(res["named"])
        self.assertEqual(res["purse"], "0.2")

    def test_no_address_no_coins(self):
        res, _ = self.board.claim(1, "Nobody", "", fin(800))
        self.assertTrue(res["record"])
        self.assertIsNone(res["purse"])
        self.assertIn("No address", res["why"])
        self.assertEqual(self.queued(), [])
        # the record still stands and a later holder with an address is paid
        res, _ = self.board.claim(1, "Bea", ADDR_B, fin(700))
        self.assertEqual(res["purse"], "0.2")

    def test_bad_claims(self):
        self.assertEqual(self.board.claim(20, "x", "", fin(1))[1], 400)
        self.assertEqual(self.board.claim(0, "", "", fin(1))[1], 400)
        self.assertEqual(self.board.claim(0, "x", "not-an-address", fin(1))[1], 400)
        self.assertEqual(self.board.claim(0, "x", "", "")[1], 400)
        self.assertEqual(self.board.claim(0, "x", "", "Z!")[1], 400)
        self.assertEqual(self.board.claim(0, "x", "", "f" + "1" * ride.MAX_LOG)[1], 400)
        self.assertEqual(self.ref.calls, 0, "nothing malformed reaches the referee")
        res, st = self.board.claim(0, "x", "", "n000")
        self.assertEqual(st, 400)
        self.assertIn("never reached", res["error"])
        res, st = self.board.claim(0, "x", "", "vvvv")
        self.assertEqual(st, 503)
        self.assertEqual(self.board.state["records"], {})

    def test_state_survives_restart(self):
        self.board.claim(2, "Marlow", ADDR_A, fin(1500))
        self.board.save()
        again = ride.Board(self.tmp.name, COURSES, self.ref, self.reg)
        self.assertEqual(again.view()[2]["name"], "Marlow")
        self.assertEqual(again.state["paid"]["2"], ride.today())
        with open(self.board.path) as f:
            self.assertIn("log", json.load(f)["records"]["2"], "the winning log is kept for audit")


class RefereeTests(unittest.TestCase):
    def test_missing_node_is_referee_down(self):
        ref = ride.Referee(os.path.join(tempfile.gettempdir(), "no-such-node"), "check.js", 2)
        with self.assertRaises(ride.RefereeDown):
            ref.replay(0, "0000")
        with self.assertRaises(ride.RefereeDown):
            ref.courses()


if __name__ == "__main__":
    unittest.main()
