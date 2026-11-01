"""Walk the Plank: prompt bank, matching, scoring and sessions (no network, judge off)."""
import json
import os
import tempfile
import unittest

from berrychain import plank
from berrychain.plank import Judge, Plank, close, load_prompts, norm

BANK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deploy", "plank-prompts.txt")


class OffJudge(Judge):
    def __init__(self):
        self.client = None
        self.model, self.per_day, self.day, self.used = "", 0, "", 0


class FakeJudge(OffJudge):
    """Pretends to be the model: anything containing 'real' is valid, canonicalised in title case."""
    def __init__(self):
        super().__init__()
        self.calls = 0

    @property
    def enabled(self):
        return True

    def ask(self, prompt, answer):
        self.calls += 1
        return answer.title() if "real" in answer.lower() else ""


def game(judge=None):
    d = tempfile.mkdtemp()
    return Plank(load_prompts(BANK), d, judge or OffJudge(), 25)


class TextTests(unittest.TestCase):
    def test_norm(self):
        self.assertEqual(norm("  The Black Pearl! "), "black pearl")
        self.assertEqual(norm("Curaçao"), "curacao")
        self.assertEqual(norm("Rock & Roll"), "rock and roll")

    def test_close(self):
        self.assertTrue(close("blackbeard", "blackbeard"))
        self.assertTrue(close("blackbeard", "blackbaerd"))      # one transposition-ish: two edits on a long word
        self.assertTrue(close("sharks", "shark"))
        self.assertFalse(close("cat", "car"))                   # short words must match exactly
        self.assertFalse(close("boat", "goat"))


class BankTests(unittest.TestCase):
    def test_bank_loads_and_ids_are_stable(self):
        ps = load_prompts(BANK)
        self.assertGreaterEqual(len(ps), 60)
        ids = [p.id for p in ps]
        self.assertEqual(len(ids), len(set(ids)), "prompt ids collide")
        for p in ps:
            self.assertGreaterEqual(len(p.canon), 8, p.text)

    def test_daily_set_is_the_same_for_everyone(self):
        g = game()
        a = [p.id for p in g.daily_set("2026-10-23")]
        b = [p.id for p in g.daily_set("2026-10-23")]
        c = [p.id for p in g.daily_set("2026-10-24")]
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertEqual(len(set(a)), 7)


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.g = game()
        self.p = next(p for p in self.g.prompts if p.text == "Name something that floats")

    def test_common_answer_scores_low_and_rare_scores_high(self):
        sid, sess, _ = self.g.new_session("endless", "Tester")
        sess["prompts"] = [self.p.id]
        res = self.g.answer(sid, self.p.id, "a boat")
        self.assertTrue(res["valid"]); self.assertEqual(res["canonical"], "Boat"); self.assertEqual(res["points"], 10)
        sid2, sess2, _ = self.g.new_session("endless", "Other")
        sess2["prompts"] = [self.p.id]
        res2 = self.g.answer(sid2, self.p.id, "pumise")                  # typo of a listed rare answer
        self.assertTrue(res2["valid"]); self.assertEqual(res2["canonical"], "Pumice"); self.assertGreaterEqual(res2["points"], 75)

    def test_unknown_answer_without_judge_scores_nothing(self):
        sid, sess, _ = self.g.new_session("endless", "Tester")
        sess["prompts"] = [self.p.id]
        res = self.g.answer(sid, self.p.id, "zxqv blorp")
        self.assertFalse(res["valid"]); self.assertEqual(res["points"], 0); self.assertIn("cannot rule", res["why"])
        self.assertEqual(self.g.answer(sid, self.p.id, "boat"), "already answered")

    def test_session_rules(self):
        sid, sess, prompts = self.g.new_session("daily", "Tester")
        self.assertEqual(len(prompts), 7)
        self.assertEqual(self.g.answer("nope", prompts[0].id, "boat"), "no such session")
        other = next(p for p in self.g.prompts if p.id not in sess["prompts"])
        self.assertEqual(self.g.answer(sid, other.id, "boat"), "that prompt is not in this dive")

    def test_board_lists_completed_named_dives(self):
        sid, sess, prompts = self.g.new_session("daily", "Deep Dan")
        for p in prompts:
            self.g.answer(sid, p.id, p.canon[-1])                        # the last listed answer: rare
        board = self.g.board(sess["day"])
        self.assertEqual(board[0]["player"], "Deep Dan")
        self.assertGreaterEqual(board[0]["depth"], 7 * 50 * 10)
        sid2, sess2, prompts2 = self.g.new_session("daily", "Quitter")
        self.g.answer(sid2, prompts2[0].id, "boat")
        self.assertEqual([r["player"] for r in self.g.board(sess["day"])], ["Deep Dan"])

    def test_state_round_trips(self):
        sid, sess, _ = self.g.new_session("endless", "Tester")
        sess["prompts"] = [self.p.id]
        self.g.answer(sid, self.p.id, "boat")
        self.g.save()
        g2 = Plank(load_prompts(BANK), self.g.dir, OffJudge(), 25)
        self.assertEqual(g2.state["counts"][self.p.id]["Boat"], 1)
        self.assertIsNotNone(g2.find_session(sid))


class JudgeTests(unittest.TestCase):
    def test_judged_answers_are_cached_and_counted(self):
        j = FakeJudge(); g = game(j)
        p = next(x for x in g.prompts if x.text == "Name something that floats")
        sid, sess, _ = g.new_session("endless", "A"); sess["prompts"] = [p.id]
        res = g.answer(sid, p.id, "a real raft thing")
        self.assertTrue(res["valid"]); self.assertEqual(res["points"], 100); self.assertEqual(res["how"], "judged")
        sid2, sess2, _ = g.new_session("endless", "B"); sess2["prompts"] = [p.id]
        res2 = g.answer(sid2, p.id, "A Real Raft Thing")
        self.assertEqual(res2["how"], "cached"); self.assertEqual(j.calls, 1)
        sid3, sess3, _ = g.new_session("endless", "C"); sess3["prompts"] = [p.id]
        bad = g.answer(sid3, p.id, "nonsense")
        self.assertFalse(bad["valid"]); self.assertEqual(j.calls, 2)


class DivePrizeTests(unittest.TestCase):
    """Past 5,000 m on the daily plank under a registered name queues 0.2 BERRY, once a day per address."""
    PIP = "brry1" + "c" * 52

    def setUp(self):
        from berrychain import params, purse
        self.params, self.purse = params, purse
        self.dir = tempfile.mkdtemp()
        reg = purse.Registry("http://127.0.0.1:1", fetch=lambda: [{"address": self.PIP, "name": "Pip"}])
        self.g = Plank(load_prompts(BANK), self.dir, OffJudge(), 25, reg)

    def dive(self, player, total, mode="daily", game=None):
        g = game or self.g
        sid, sess, prompts = g.new_session(mode, player)
        sess["total"] = total
        sess["answers"] = {p.id: {"raw": "x", "canon": "x", "points": 0} for p in prompts}
        return g.dive_prize(sess)

    def queued(self):
        return [e for _, e in self.purse.pending([os.path.join(self.dir, "queue")])]

    def test_registered_name_is_paid_once_a_day(self):
        res = self.dive("pip", 520)
        self.assertTrue(res["paid"]); self.assertEqual(res["amount"], "0.2"); self.assertEqual(res["to"], self.PIP)
        q = self.queued()
        self.assertEqual(len(q), 1)
        self.assertEqual((q[0]["kind"], q[0]["amount"], q[0]["ref"]["depth"]), ("plank-dive", self.params.PURSE_PLANK_DIVE, 5200))
        self.assertIn("5,200 metres", q[0]["body"])
        again = self.dive("Pip", 700)
        self.assertFalse(again["paid"]); self.assertIn("already been paid", again["why"])
        self.assertEqual(len(self.queued()), 1)

    def test_shallow_unnamed_unregistered_endless_and_shut_dives_pay_nothing(self):
        self.assertIsNone(self.dive("Pip", 499))
        self.assertIsNone(self.dive("Pip", 700, mode="endless"))
        self.assertFalse(self.dive("", 600)["paid"])
        res = self.dive("Pegleg Pete", 600)
        self.assertFalse(res["paid"]); self.assertIn("not a registered", res["why"])
        shut = Plank(load_prompts(BANK), tempfile.mkdtemp(), OffJudge(), 25)
        self.assertIn("shut", self.dive("Pip", 600, game=shut)["why"])
        self.assertEqual(self.queued(), [])

    def test_prize_rides_on_the_seventh_answer(self):
        sid, sess, prompts = self.g.new_session("daily", "Pip")
        for p in prompts[:5]:
            self.g.answer(sid, p.id, p.canon[0])
        sixth = self.g.answer(sid, prompts[5].id, prompts[5].canon[0])
        self.assertNotIn("prize", sixth)
        sess["total"] = 600
        last = self.g.answer(sid, prompts[6].id, prompts[6].canon[0])
        self.assertTrue(last["prize"]["paid"])
        self.assertEqual(len(self.queued()), 1)
        sid2, sess2, prompts2 = self.g.new_session("daily", "Pegleg")
        for p in prompts2[:6]:
            self.g.answer(sid2, p.id, p.canon[0])
        self.assertIsNone(self.g.answer(sid2, prompts2[6].id, prompts2[6].canon[0])["prize"], "a shallow dive carries prize: null")


if __name__ == "__main__":
    unittest.main()
