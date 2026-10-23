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


if __name__ == "__main__":
    unittest.main()
