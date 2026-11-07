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

    def ask(self, prompt, answer, examples=(), fact=False):
        self.calls += 1
        self.examples = list(examples)
        self.fact = fact
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
            self.assertGreaterEqual(len(p.canon), 1 if p.fact else 3, p.text)

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


class FactTests(unittest.TestCase):
    """Single-answer questions: 100 or nothing, two in every seven."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        path = os.path.join(self.dir, "bank.txt")
        with open(BANK, encoding="utf-8") as src, open(path, "w", encoding="utf-8") as f:
            f.write(src.read())
            f.write("\n= Which continent has no Formula 1 race | Africa, Antarctica\n"
                    "= What is the capital of Australia | Canberra\n"
                    "= Which river runs through Paris | Seine=The Seine\n")
        self.judge = FakeJudge()
        self.g = Plank(load_prompts(path), self.dir, self.judge, 25)
        self.facts = [p for p in self.g.prompts if p.fact]

    def test_fact_lines_load_and_fill_two_of_seven(self):
        self.assertGreaterEqual(len(self.facts), 3)
        self.assertIn("Which continent has no Formula 1 race", [p.text for p in self.facts])
        for day in ("2026-11-07", "2026-11-08", "2026-11-09"):
            chosen = self.g.daily_set(day)
            self.assertEqual(len(chosen), 7)
            self.assertEqual(sum(1 for p in chosen if p.fact), plank.FACT_PER_DAY)
        self.assertEqual(self.g.daily_set("2026-11-07"), self.g.daily_set("2026-11-07"), "deterministic per day")

    def test_fact_scores_100_or_nothing(self):
        p = next(x for x in self.facts if x.text.startswith("Which continent"))
        for i, (raw, want) in enumerate([("africa", 100), ("Antartica", 100), ("Europe", 0), ("", 0), ("africa", 100)]):
            sid, sess, _ = self.g.new_session("endless", f"P{i}"); sess["prompts"] = [p.id]
            res = self.g.answer(sid, p.id, raw)
            self.assertEqual(res["points"], want, raw)
            self.assertEqual(res["kind"], "fact")
            if want == 0 and raw:
                self.assertIn("The answer: Africa or Antarctica", res["why"])
        self.assertTrue(self.judge.fact, "the judge was asked in single-answer mode")

class JudgeMaintenanceTests(unittest.TestCase):
    def test_forget_invalid_drops_only_rejections(self):
        j = FakeJudge()
        g = game(j)
        p = g.prompts[0]
        sid, sess, _ = g.new_session("endless", "A"); sess["prompts"] = [p.id]
        g.answer(sid, p.id, "nonsense")
        self.assertEqual(j.examples, p.canon[:8], "the judge is shown the listed answers")
        sid2, sess2, _ = g.new_session("endless", "B"); sess2["prompts"] = [p.id]
        g.answer(sid2, p.id, "a real thing")
        g.save()
        self.assertEqual(set(g.state["judged"][p.id].values()), {"", "A Real Thing"})
        self.assertEqual(plank.forget_invalid(g.path), 1)
        with open(g.path) as f:
            kept = json.load(f)["judged"][p.id]
        self.assertEqual(list(kept.values()), ["A Real Thing"])


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


class BoardTests(unittest.TestCase):
    """One row per name, deepest dive wins, today or the Monday-to-Sunday week."""

    def setUp(self):
        from berrychain import purse
        reg = purse.Registry("http://127.0.0.1:1", fetch=lambda: [{"address": "brry1" + "c" * 52, "name": "Pip"}])
        self.g = Plank(load_prompts(BANK), tempfile.mkdtemp(), OffJudge(), 25, reg)
        self.pids = [p.id for p in self.g.prompts[:7]]

    def dive(self, day, player, total, answers=7):
        sess = {"mode": "daily", "day": day, "player": player, "prompts": self.pids, "total": total, "started": 0,
                "answers": {pid: {"raw": "x", "canon": "x", "points": 0} for pid in self.pids[:answers]}}
        self.g._day(day)["sessions"][f"{day}-{player}-{total}"] = sess

    def test_plank_day_turns_at_five_am_sydney(self):
        import datetime as dt
        from berrychain.plank import Plank, DAY_TZ
        before = dt.datetime(2026, 11, 3, 4, 59, tzinfo=DAY_TZ)
        after = dt.datetime(2026, 11, 3, 5, 0, tzinfo=DAY_TZ)
        self.assertEqual(Plank.today(before), "2026-11-02")
        self.assertEqual(Plank.today(after), "2026-11-03")
        utc_midnight = dt.datetime(2026, 11, 3, 0, 0, tzinfo=dt.timezone.utc)   # 11 am in Sydney: still the 3rd
        self.assertEqual(Plank.today(utc_midnight), "2026-11-03")

    def test_week_of(self):
        self.assertEqual(self.g.week_of("2026-11-04")[0], "2026-11-02")
        self.assertEqual(self.g.week_of("2026-11-08"), [f"2026-11-0{i}" for i in range(2, 9)])
        self.assertEqual(self.g.week_of("2026-11-09")[0], "2026-11-09")

    def test_boards(self):
        self.dive("2026-11-03", "Pip", 520)
        self.dive("2026-11-03", "pip", 300)             # same person, shallower: one row
        self.dive("2026-11-03", "Pegleg", 610)
        self.dive("2026-11-03", "Quiet", 700, answers=6)  # unfinished: not on the board
        self.dive("2026-11-03", "", 700)                 # nameless: not on the board
        self.dive("2026-11-05", "Pip", 650)
        self.dive("2026-11-01", "Pegleg", 690)           # Sunday before: last week
        day = self.g.board("2026-11-03")
        self.assertEqual([(r["player"], r["depth"], r["named"]) for r in day], [("Pegleg", 6100, False), ("Pip", 5200, True)])
        self.assertEqual(day[1]["dives"], 2)
        week = self.g.week_board("2026-11-04")
        self.assertEqual([(r["player"], r["depth"], r["day"]) for r in week], [("Pip", 6500, "2026-11-05"), ("Pegleg", 6100, "2026-11-03")])
        self.assertEqual(week[0]["dives"], 3)
        self.assertEqual(self.g.week_board("2026-11-01")[0]["depth"], 6900)
        self.assertEqual(self.g.board("2026-11-04"), [])


if __name__ == "__main__":
    unittest.main()
