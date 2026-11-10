"""Walk the Plank: the captain's daily trivia dive (see docs/PLANK.md).

Seven prompts a day, the same seven for everyone. Each answer is scored by how
rare it is among all the answers given so far: a common answer is worth 10
points, the rarest 100. Points are fathoms; a perfect dive is 7,000 metres.

This is a small stand-alone HTTP service, fronted by nginx at /plank/ like the
push relay and the parcel room. State is a JSON file. Unknown answers are judged
once by a model (if ANTHROPIC_API_KEY is set) and the verdict is cached, so a
given spelling is never judged twice.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import random
import re
import secrets
import sys
import threading
import time
import unicodedata
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from . import params, purse

TIERS = [(0.25, 10), (0.12, 20), (0.06, 30), (0.03, 50), (0.01, 75), (0.0, 100)]
PRIOR = [20, 12, 8, 5, 4, 3, 3, 2]          # weight of the bank's listed answers, in order; the rest get 1
DAILY_PROMPTS = 7
FACT_PER_DAY = 2          # of the seven, this many have one right answer (100 points or nothing)
NO_REPEAT_DAYS = 30       # a question used in the last this-many plank days is not drawn again
NO_REPEAT_FROM = "2026-11-11"   # the first plank day drawn under that rule (earlier days were independent draws)
MAX_ANSWER = 60
MAX_PLAYER = 24
KEEP_DAYS = 90
DAY_START_HOUR = int(os.environ.get("PLANK_DAY_START_HOUR", "5"))   # the new plank goes up at this hour, local time
try:
    from zoneinfo import ZoneInfo
    DAY_TZ = ZoneInfo(os.environ.get("PLANK_TZ", "Australia/Sydney"))
except Exception:  # pragma: no cover  no tz database (some Windows installs): fall back to AEDT
    DAY_TZ = dt.timezone(dt.timedelta(hours=11), "AEDT")
ORIGINS = {"https://berrychain.link", "https://www.berrychain.link", "http://localhost:8765", "http://127.0.0.1:8765"}


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


# ------------------------------------------------------------------ text
def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower()
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    for art in ("the ", "a ", "an "):
        if s.startswith(art) and len(s) > len(art) + 2:
            s = s[len(art):]
    return s


def lev(a: str, b: str, cap: int) -> int:
    """Levenshtein distance, giving up (returning cap + 1) once it cannot be within cap."""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        best = i
        for j, cb in enumerate(b, 1):
            v = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
            cur.append(v)
            best = min(best, v)
        if best > cap:
            return cap + 1
        prev = cur
    return prev[-1]


def close(a: str, b: str) -> bool:
    if a == b:
        return True
    if a.rstrip("s") == b.rstrip("s") and min(len(a), len(b)) >= 3:
        return True
    n = min(len(a), len(b))
    cap = 2 if n >= 9 else 1 if n >= 5 else 0
    return cap > 0 and lev(a, b, cap) <= cap


# ------------------------------------------------------------------ prompts
class Prompt:
    def __init__(self, text: str, answers: list[list[str]], fact: bool = False):
        self.text = text
        self.fact = fact                              # one right answer: 100 points or nothing, rarity does not apply
        self.id = hashlib.sha1(norm(text).encode()).hexdigest()[:8]
        self.canon: list[str] = [a[0] for a in answers]
        self.alias: dict[str, str] = {}              # normalised alias -> canonical
        for group in answers:
            for name in group:
                self.alias.setdefault(norm(name), group[0])

    def prior(self) -> dict[str, int]:
        return {c: (PRIOR[i] if i < len(PRIOR) else 1) for i, c in enumerate(self.canon)}


def load_prompts(path: str) -> list[Prompt]:
    out: list[Prompt] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "|" not in line:
                continue
            text, rest = line.split("|", 1)
            fact = text.lstrip().startswith("=")           # '= Which ... | Answer' marks a single-answer question
            text = text.lstrip().lstrip("=").strip()
            answers = [[p.strip() for p in a.split("=") if p.strip()] for a in rest.split(",") if a.strip()]
            if text and answers:
                out.append(Prompt(text, answers, fact=fact))
    if len(out) < DAILY_PROMPTS:
        raise SystemExit(f"plank: need at least {DAILY_PROMPTS} prompts in {path}")
    return out


# ------------------------------------------------------------------ judge
class Judge:
    """Asks a model whether an unlisted answer is a genuine answer to the prompt. One call per new spelling."""

    SYSTEM = (
        "You judge answers for a pub-style trivia game played mostly by Australians. You are given the prompt, a few "
        "answers already on the list (to show the kind of thing wanted), and a player's answer. Decide whether a fair "
        "pub-quiz host would accept the player's answer as a real, specific answer to the prompt.\n"
        "Accept: correct answers in any spelling; partial or short names that clearly identify one thing (Brett Lee; "
        "Rialto for the Rialto Bridge; Bounty for HMS Bounty; London for London Bridge when the prompt is bridges); "
        "brand, model and product names; less famous members of the category; regional and Australian answers; "
        "plurals and loose phrasing (car broke down; you are sick). When in doubt, accept.\n"
        "Reject only: made-up words; the wrong category (a capital when the prompt wants a non-capital, a Central "
        "American country for South America); answers too vague to name one specific thing (steve, flower, drive, "
        "lights); rude answers; or answers that only repeat the prompt's own words.\n"
        "Reply with one line of JSON only: {\"valid\": true, \"canonical\": \"Proper Name\"} or "
        "{\"valid\": false, \"why\": \"short reason\"}. The canonical form is the usual name in title case, no "
        "article, the fullest common form (Brett Lee, HMS Bounty, London Bridge, Rialto Bridge).")

    def __init__(self, model: str, per_day: int):
        self.model, self.per_day = model, per_day
        self.client = None
        self.day, self.used = "", 0
        if env("ANTHROPIC_API_KEY"):
            try:
                import anthropic
                self.client = anthropic.Anthropic()
            except Exception as e:  # pragma: no cover
                print(f"plank: judge disabled ({e})", flush=True)

    @property
    def enabled(self) -> bool:
        return self.client is not None

    SYSTEM_FACT = (
        "You check a trivia question that has one right answer (or a few equivalent ones). You are given the question, "
        "the accepted answer(s), and a player's answer. Say whether the player's answer means the same thing as an "
        "accepted answer: spelling mistakes, abbreviations, and other names for the same thing count (Uluru for Ayers "
        "Rock, USA for United States); a different thing does not, however close. Reply with one line of JSON only: "
        "{\"valid\": true, \"canonical\": \"<the accepted answer as listed>\"} or {\"valid\": false}.")

    def ask(self, prompt: str, answer: str, examples: tuple[str, ...] | list[str] = (), fact: bool = False) -> str | None:
        """Returns the canonical form if valid, '' if invalid, None if the judge could not run."""
        if not self.client:
            return None
        today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
        if today != self.day:
            self.day, self.used = today, 0
        if self.used >= self.per_day:
            return None
        self.used += 1
        try:
            shown = ", ".join(list(examples)[:8]) or "(none listed yet)"
            if fact:
                content = f"Question: {prompt}\nAccepted answer(s): {shown}\nPlayer's answer: {answer[:MAX_ANSWER]}"
            else:
                content = f"Prompt: {prompt}\nAlready on the list: {shown}\nPlayer's answer: {answer[:MAX_ANSWER]}"
            resp = self.client.messages.create(
                model=self.model, max_tokens=120, system=self.SYSTEM_FACT if fact else self.SYSTEM,
                messages=[{"role": "user", "content": content}])
            text = "".join(getattr(b, "text", "") for b in resp.content)
            m = re.search(r"\{.*\}", text, re.S)
            data = json.loads(m.group(0)) if m else {}
            if data.get("valid") and isinstance(data.get("canonical"), str) and data["canonical"].strip():
                return data["canonical"].strip()[:MAX_ANSWER]
            return ""
        except Exception as e:
            print(f"plank: judge error: {e}", flush=True)
            return None


# ------------------------------------------------------------------ game
class Plank:
    def __init__(self, prompts: list[Prompt], data_dir: str, judge: Judge, seconds: int, registry: purse.Registry | None = None):
        self.prompts = prompts
        self._sets: dict[str, list[Prompt]] = {}      # plank day -> its seven, memoised (deterministic per bank)
        self.registry = registry                      # registered names -> addresses; None keeps the purse shut
        self.queue = os.path.join(data_dir, "queue")   # prizes for the Harbourmaster to pay (berrychain/purse.py)
        self.by_id = {p.id: p for p in prompts}
        self.dir = data_dir
        self.path = os.path.join(data_dir, "plank-state.json")
        self.judge = judge
        self.seconds = seconds
        self.lock = threading.Lock()
        self.state: dict[str, Any] = {"counts": {}, "judged": {}, "days": {}, "endless": {}, "dive_paid": {}}
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as f:
                self.state.update(json.load(f))

    # -- persistence
    def save(self) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.state, f, separators=(",", ":"))
        os.replace(tmp, self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    # -- days
    @staticmethod
    def today(now: dt.datetime | None = None) -> str:
        """The plank day: a new plank at DAY_START_HOUR in DAY_TZ (5 am Sydney), not at midnight UTC."""
        now = now or dt.datetime.now(dt.timezone.utc)
        local = now.astimezone(DAY_TZ) - dt.timedelta(hours=DAY_START_HOUR)
        return local.strftime("%Y-%m-%d")

    def _mix(self, rng: random.Random, exclude: frozenset[str] = frozenset()) -> list[Prompt]:
        """Seven prompts: FACT_PER_DAY single-answer ones (when the bank has them) and the rest open, shuffled.
        Prompts in `exclude` (recently used) are left out while the bank is big enough to allow it."""
        facts = [p for p in self.prompts if p.fact and p.id not in exclude]
        opens = [p for p in self.prompts if not p.fact and p.id not in exclude]
        nf = min(FACT_PER_DAY, len(facts))
        if len(opens) < DAILY_PROMPTS - nf:
            if exclude:                                   # bank too small to avoid repeats: draw from all of it
                return self._mix(rng)
            return rng.sample(self.prompts, DAILY_PROMPTS)
        chosen = rng.sample(facts, nf) + rng.sample(opens, DAILY_PROMPTS - nf)
        rng.shuffle(chosen)
        return chosen

    def daily_set(self, day: str) -> list[Prompt]:
        """The seven for a plank day: the same for everyone, drawn from the day alone (no state), and from
        NO_REPEAT_FROM on never a prompt used in the previous NO_REPEAT_DAYS days."""
        got = self._sets.get(day)
        if got is not None:
            return got
        if day >= NO_REPEAT_FROM:
            # every day from the rule's start up to this one, oldest first, so each sees the days before it
            start = dt.date.fromisoformat(NO_REPEAT_FROM)
            d = start
            while d.isoformat() < day:
                self.daily_set(d.isoformat())
                d += dt.timedelta(days=1)
            recent: set[str] = set()
            this = dt.date.fromisoformat(day)
            for back in range(1, NO_REPEAT_DAYS + 1):
                recent.update(p.id for p in self.daily_set((this - dt.timedelta(days=back)).isoformat()))
            exclude = frozenset(recent)
        else:
            exclude = frozenset()
        seed = int(hashlib.sha256(("plank|" + day).encode()).hexdigest()[:12], 16)
        chosen = self._mix(random.Random(seed), exclude)
        self._sets[day] = chosen
        return chosen

    def _day(self, day: str) -> dict[str, Any]:
        d = self.state["days"].setdefault(day, {"sessions": {}})
        if len(self.state["days"]) > KEEP_DAYS:
            for old in sorted(self.state["days"])[:-KEEP_DAYS]:
                self.state["days"].pop(old, None)
        return d

    def new_session(self, mode: str, player: str) -> tuple[str, dict[str, Any], list[Prompt]]:
        sid = secrets.token_urlsafe(12)
        day = self.today()
        if mode == "daily":
            prompts = self.daily_set(day)
            bucket = self._day(day)["sessions"]
        else:
            prompts = self._mix(random.Random())
            bucket = self.state["endless"]
            if len(bucket) > 400:
                for old in list(bucket)[:-400]:
                    bucket.pop(old, None)
        sess = {"mode": mode, "day": day, "player": player, "prompts": [p.id for p in prompts], "answers": {}, "total": 0,
                "started": int(time.time())}
        bucket[sid] = sess
        return sid, sess, prompts

    def find_session(self, sid: str) -> dict[str, Any] | None:
        s = self.state["endless"].get(sid)
        if s:
            return s
        for d in self.state["days"].values():
            if sid in d["sessions"]:
                return d["sessions"][sid]
        return None

    # -- scoring
    def resolve(self, p: Prompt, raw: str) -> tuple[str | None, str]:
        """-> (canonical or None, how) where how is list / fuzzy / judged / cached / unknown / nojudge."""
        n = norm(raw)
        if not n:
            return None, "empty"
        if n in p.alias:
            return p.alias[n], "list"
        judged = self.state["judged"].setdefault(p.id, {})
        if n in judged:
            return (judged[n] or None), "cached"
        known = {**p.alias, **{norm(c): c for c in self.state["counts"].get(p.id, {})}}
        for k, c in known.items():
            if close(n, k):
                return c, "fuzzy"
        verdict = self.judge.ask(p.text, raw, p.canon[:8], fact=p.fact)
        if verdict is None:
            return None, "nojudge"
        # the judge may hand back a name we already count under another spelling
        vn = norm(verdict) if verdict else ""
        if vn:
            for k, c in known.items():
                if close(vn, k):
                    verdict = c
                    break
        judged[n] = verdict
        return (verdict or None), "judged"

    def tier(self, p: Prompt, canon: str) -> tuple[int, float, int]:
        counts = {**p.prior()}
        for c, n in self.state["counts"].get(p.id, {}).items():
            counts[c] = counts.get(c, 0) + n
        total = sum(counts.values()) or 1
        share = counts.get(canon, 0) / total
        if p.fact:
            return 100, share, total          # one right answer: the full 100, however many got it
        for cut, pts in TIERS:
            if share >= cut:
                return pts, share, total
        return 100, share, total

    def top(self, p: Prompt, k: int = 6) -> list[list[Any]]:
        counts = {**p.prior()}
        for c, n in self.state["counts"].get(p.id, {}).items():
            counts[c] = counts.get(c, 0) + n
        return [[c, n] for c, n in sorted(counts.items(), key=lambda kv: -kv[1])[:k]]

    def answer(self, sid: str, pid: str, raw: str) -> dict[str, Any] | str:
        sess = self.find_session(sid)
        if not sess:
            return "no such session"
        if pid not in sess["prompts"]:
            return "that prompt is not in this dive"
        if pid in sess["answers"]:
            return "already answered"
        p = self.by_id.get(pid)
        if not p:
            return "unknown prompt"
        raw = (raw or "").strip()[:MAX_ANSWER]
        canon, how = self.resolve(p, raw) if raw else (None, "empty")
        if canon is None:
            sess["answers"][pid] = {"raw": raw, "canon": None, "points": 0}
            msg = {"empty": "You froze on the plank.", "nojudge": "The captain cannot rule on that one right now.",
                   "unknown": "The captain does not recognise that one."}.get(how, "The captain does not recognise that one.")
            if p.fact and how != "nojudge":
                msg = ("You froze on the plank. " if how == "empty" else "Not this one. ") + "The answer: " + " or ".join(p.canon[:3]) + "."
            return {"valid": False, "points": 0, "why": msg, "top": self.top(p), "total": sess["total"],
                    "kind": "fact" if p.fact else "open"}
        pts, share, total = self.tier(p, canon)
        self.state["counts"].setdefault(pid, {})
        self.state["counts"][pid][canon] = self.state["counts"][pid].get(canon, 0) + 1
        sess["answers"][pid] = {"raw": raw, "canon": canon, "points": pts}
        sess["total"] += pts
        out = {"valid": True, "canonical": canon, "points": pts, "share": round(share, 4), "answers_seen": total,
               "how": how, "top": self.top(p), "total": sess["total"], "kind": "fact" if p.fact else "open"}
        if len(sess["answers"]) == DAILY_PROMPTS:
            out["prize"] = self.dive_prize(sess)
        return out

    # -- the dive prize: 0.2 BERRY for passing PLANK_PRIZE_DEPTH on the daily plank, once a day per registered name
    def dive_prize(self, sess: dict[str, Any]) -> dict[str, Any] | None:
        """Called once, when the seventh answer lands. Queues the prize and says what happened, or None when the dive was not deep enough."""
        depth = sess["total"] * 10
        if sess.get("mode") != "daily" or depth < params.PLANK_PRIZE_DEPTH:
            return None
        amount = purse.berry_str(params.PURSE_PLANK_DIVE)
        if self.registry is None:
            return {"paid": False, "why": "The race purse is shut on this log."}
        name = sess.get("player") or ""
        if not name:
            return {"paid": False, "why": f"Past {params.PLANK_PRIZE_DEPTH:,} m: that earns {amount} BERRY when you dive under your registered BerryChain name."}
        addr = self.registry.address_of(name)
        if not addr:
            return {"paid": False, "why": f"Past {params.PLANK_PRIZE_DEPTH:,} m. '{name}' is not a registered BerryChain name, so the {amount} BERRY stays in the purse; register the name in the app and dive under it."}
        day = sess.get("day") or self.today()
        paid = self.state.setdefault("dive_paid", {})
        if len(paid) > KEEP_DAYS:
            for old in sorted(paid)[:-KEEP_DAYS]:
                paid.pop(old, None)
        if addr in paid.setdefault(day, []):
            return {"paid": False, "why": f"Past {params.PLANK_PRIZE_DEPTH:,} m again, but {name} has already been paid for today's plank."}
        body = (f"You walked today's plank ({day}) to {depth:,} metres, past the {params.PLANK_PRIZE_DEPTH:,} m mark. "
                f"The dive prize rides with this letter: {amount} BERRY. Once a day per registered name; the next seven are up tomorrow. "
                "BERRY has no price and no value; it is the coin you write letters with.")
        purse.enqueue(self.queue, "plank-dive", addr, params.PURSE_PLANK_DIVE, f"Walk the Plank: {depth:,} m on {day}", body,
                      ref={"day": day, "depth": depth, "name": name})
        paid[day].append(addr)
        return {"paid": True, "amount": amount, "to": addr,
                "why": f"Past {params.PLANK_PRIZE_DEPTH:,} m under a registered name: {amount} BERRY is on its way to {name}'s chest as a letter from the Harbourmaster."}

    # -- boards: the deepest named, completed dives, one row per name (deepest dive wins), today or this week
    @staticmethod
    def week_of(day: str) -> list[str]:
        d = dt.date.fromisoformat(day)
        monday = d - dt.timedelta(days=d.weekday())
        return [(monday + dt.timedelta(days=i)).isoformat() for i in range(7)]

    def _named(self, player: str) -> bool:
        return bool(self.registry and self.registry.address_of(player))

    def _best(self, days: list[str]) -> list[dict[str, Any]]:
        best: dict[str, dict[str, Any]] = {}
        for day in days:
            for s in self.state["days"].get(day, {"sessions": {}})["sessions"].values():
                if not s.get("player") or len(s["answers"]) != DAILY_PROMPTS:
                    continue
                key = norm(s["player"]) or s["player"].lower()
                depth = s["total"] * 10
                cur = best.get(key)
                dives = (cur["dives"] if cur else 0) + 1
                if cur is None or depth > cur["depth"]:
                    best[key] = {"player": s["player"], "depth": depth, "day": day, "dives": dives}
                else:
                    cur["dives"] = dives
        rows = sorted(best.values(), key=lambda r: (-r["depth"], r["day"], r["player"]))[:20]
        for r in rows:
            r["named"] = self._named(r["player"])
        return rows

    def board(self, day: str) -> list[dict[str, Any]]:
        return self._best([day])

    def week_board(self, day: str) -> list[dict[str, Any]]:
        return self._best(self.week_of(day))


# ------------------------------------------------------------------ http
def make_handler(game: Plank):
    class Handler(BaseHTTPRequestHandler):
        server_version = "BerryChainPlank/1"

        def log_message(self, fmt, *args):  # quiet
            pass

        def _cors(self):
            origin = self.headers.get("Origin", "")
            if origin in ORIGINS:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Max-Age", "600")

        def _send(self, obj: Any, status: int = 200) -> None:
            body = json.dumps(obj).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self._cors()
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):
            self.send_response(204)
            self._cors()
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _query(self) -> dict[str, str]:
            if "?" not in self.path:
                return {}
            out = {}
            for part in self.path.split("?", 1)[1].split("&"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    out[k] = v
            return out

        def do_GET(self):
            route = self.path.split("?")[0]
            q = self._query()
            with game.lock:
                if route == "/plank/status":
                    answered = sum(sum(c.values()) for c in game.state["counts"].values())
                    return self._send({"prompts": len(game.prompts), "facts": sum(1 for p in game.prompts if p.fact), "answers": answered, "day": game.today(),
                                       "judge": game.judge.enabled, "seconds": game.seconds, "purse": game.registry is not None,
                                       "prize": {"depth": params.PLANK_PRIZE_DEPTH, "amount": purse.berry_str(params.PURSE_PLANK_DIVE)}})
                if route in ("/plank/today", "/plank/endless"):
                    mode = "daily" if route.endswith("today") else "endless"
                    player = re.sub(r"[^\w .'-]", "", (q.get("player", "")))[:MAX_PLAYER].strip()
                    sid, sess, prompts = game.new_session(mode, player)
                    game.save()
                    return self._send({"session": sid, "mode": mode, "day": sess["day"], "seconds": game.seconds,
                                       "prompts": [{"id": p.id, "text": p.text, "kind": "fact" if p.fact else "open"} for p in prompts]})
                if route == "/plank/board":
                    day = q.get("day", game.today())
                    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
                        return self._send({"error": "bad day"}, 400)
                    if q.get("range") == "week":
                        week = game.week_of(day)
                        return self._send({"day": day, "range": "week", "week": [week[0], week[-1]], "board": game.week_board(day)})
                    return self._send({"day": day, "range": "day", "board": game.board(day)})
                if route == "/plank/reveal":
                    p = game.by_id.get(q.get("pid", ""))
                    if not p:
                        return self._send({"error": "unknown prompt"}, 404)
                    return self._send({"id": p.id, "text": p.text, "top": game.top(p, 8)})
            return self._send({"error": "not found"}, 404)

        def do_POST(self):
            route = self.path.split("?")[0]
            if route != "/plank/answer":
                return self._send({"error": "not found"}, 404)
            try:
                n = int(self.headers.get("Content-Length", "0"))
                if n > 2048:
                    return self._send({"error": "too large"}, 413)
                body = json.loads(self.rfile.read(n) or b"{}")
            except Exception:
                return self._send({"error": "bad json"}, 400)
            sid, pid, raw = str(body.get("session", ""))[:40], str(body.get("pid", ""))[:16], str(body.get("answer", ""))
            player = re.sub(r"[^\w .'-]", "", str(body.get("player", "")))[:MAX_PLAYER].strip()
            with game.lock:                       # one answer at a time; a judge call is a second or so
                sess = game.find_session(sid)
                if sess is not None and player and not sess.get("player"):
                    sess["player"] = player
                res = game.answer(sid, pid, raw)
                game.save()
            if isinstance(res, str):
                return self._send({"error": res}, 400)
            return self._send(res)

    return Handler


def forget_invalid(state_path: str) -> int:
    """Drop every cached 'invalid' verdict so those spellings are judged again (after a judge change). Returns how many."""
    if not os.path.exists(state_path):
        return 0
    with open(state_path, encoding="utf-8") as f:
        state = json.load(f)
    n = 0
    for pid, verdicts in list(state.get("judged", {}).items()):
        for spelling in [s for s, v in verdicts.items() if not v]:
            del verdicts[spelling]
            n += 1
    tmp = state_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, separators=(",", ":"))
    os.replace(tmp, state_path)
    return n


def main(argv=None) -> None:
    port = int(env("PLANK_PORT", "8805"))
    data_dir = env("PLANK_DIR") or ("/var/lib/berrychain/plank" if os.name != "nt" else os.path.join(os.environ.get("TEMP", "."), "berrychain-plank"))
    if argv and argv[0] == "forget-invalid":          # maintenance, with the service stopped
        print(f"plank: forgot {forget_invalid(os.path.join(data_dir, 'plank-state.json'))} invalid verdict(s)", flush=True)
        return
    prompts_path = env("PLANK_PROMPTS", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deploy", "plank-prompts.txt"))
    os.makedirs(data_dir, exist_ok=True)
    prompts = load_prompts(prompts_path)
    judge = Judge(env("PLANK_MODEL", "claude-sonnet-5-5"), int(env("PLANK_JUDGE_PER_DAY", "3000")))
    node_url = env("PLANK_NODE_URL", "http://127.0.0.1:8801")
    registry = purse.Registry(node_url) if node_url and node_url != "off" else None
    game = Plank(prompts, data_dir, judge, int(env("PLANK_SECONDS", "25")), registry)
    print(f"plank: {len(prompts)} prompts, judge {'on' if judge.enabled else 'off'}, purse {'open' if registry else 'shut'}, port {port}", flush=True)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(game))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main(sys.argv[1:])
