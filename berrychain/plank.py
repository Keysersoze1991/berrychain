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

TIERS = [(0.25, 10), (0.12, 20), (0.06, 30), (0.03, 50), (0.01, 75), (0.0, 100)]
PRIOR = [20, 12, 8, 5, 4, 3, 3, 2]          # weight of the bank's listed answers, in order; the rest get 1
DAILY_PROMPTS = 7
MAX_ANSWER = 60
MAX_PLAYER = 24
KEEP_DAYS = 90
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
    def __init__(self, text: str, answers: list[list[str]]):
        self.text = text
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
            answers = [[p.strip() for p in a.split("=") if p.strip()] for a in rest.split(",") if a.strip()]
            if text.strip() and answers:
                out.append(Prompt(text.strip(), answers))
    if len(out) < DAILY_PROMPTS:
        raise SystemExit(f"plank: need at least {DAILY_PROMPTS} prompts in {path}")
    return out


# ------------------------------------------------------------------ judge
class Judge:
    """Asks a model whether an unlisted answer is a genuine answer to the prompt. One call per new spelling."""

    SYSTEM = ("You judge answers for a pub-style trivia game. Given a prompt like 'Name a famous pirate' and a "
              "player's answer, decide whether the answer is a real, correct, specific answer to the prompt. "
              "Be generous with spelling and with regional knowledge (the players are mostly Australian), strict "
              "with made-up, vague, rude or off-topic answers. Reply with one line of JSON only: "
              '{"valid": true, "canonical": "Proper Name"} or {"valid": false}. The canonical form is the usual '
              "short name in title case, no article.")

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

    def ask(self, prompt: str, answer: str) -> str | None:
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
            resp = self.client.messages.create(
                model=self.model, max_tokens=80, system=self.SYSTEM,
                messages=[{"role": "user", "content": f"Prompt: {prompt}\nAnswer: {answer[:MAX_ANSWER]}"}])
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
    def __init__(self, prompts: list[Prompt], data_dir: str, judge: Judge, seconds: int):
        self.prompts = prompts
        self.by_id = {p.id: p for p in prompts}
        self.dir = data_dir
        self.path = os.path.join(data_dir, "plank-state.json")
        self.judge = judge
        self.seconds = seconds
        self.lock = threading.Lock()
        self.state: dict[str, Any] = {"counts": {}, "judged": {}, "days": {}, "endless": {}}
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
    def today() -> str:
        return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")

    def daily_set(self, day: str) -> list[Prompt]:
        seed = int(hashlib.sha256(("plank|" + day).encode()).hexdigest()[:12], 16)
        return random.Random(seed).sample(self.prompts, DAILY_PROMPTS)

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
            prompts = random.sample(self.prompts, DAILY_PROMPTS)
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
        verdict = self.judge.ask(p.text, raw)
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
            return {"valid": False, "points": 0, "why": msg, "top": self.top(p), "total": sess["total"]}
        pts, share, total = self.tier(p, canon)
        self.state["counts"].setdefault(pid, {})
        self.state["counts"][pid][canon] = self.state["counts"][pid].get(canon, 0) + 1
        sess["answers"][pid] = {"raw": raw, "canon": canon, "points": pts}
        sess["total"] += pts
        return {"valid": True, "canonical": canon, "points": pts, "share": round(share, 4), "answers_seen": total,
                "how": how, "top": self.top(p), "total": sess["total"]}

    def board(self, day: str) -> list[dict[str, Any]]:
        d = self.state["days"].get(day, {"sessions": {}})
        rows = [{"player": s["player"], "depth": s["total"] * 10}
                for s in d["sessions"].values() if s.get("player") and len(s["answers"]) == DAILY_PROMPTS]
        rows.sort(key=lambda r: -r["depth"])
        return rows[:20]


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
                    return self._send({"prompts": len(game.prompts), "answers": answered, "day": game.today(),
                                       "judge": game.judge.enabled, "seconds": game.seconds})
                if route in ("/plank/today", "/plank/endless"):
                    mode = "daily" if route.endswith("today") else "endless"
                    player = re.sub(r"[^\w .'-]", "", (q.get("player", "")))[:MAX_PLAYER].strip()
                    sid, sess, prompts = game.new_session(mode, player)
                    game.save()
                    return self._send({"session": sid, "mode": mode, "day": sess["day"], "seconds": game.seconds,
                                       "prompts": [{"id": p.id, "text": p.text} for p in prompts]})
                if route == "/plank/board":
                    day = q.get("day", game.today())
                    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
                        return self._send({"error": "bad day"}, 400)
                    return self._send({"day": day, "board": game.board(day)})
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


def main(argv=None) -> None:
    port = int(env("PLANK_PORT", "8805"))
    data_dir = env("PLANK_DIR") or ("/var/lib/berrychain/plank" if os.name != "nt" else os.path.join(os.environ.get("TEMP", "."), "berrychain-plank"))
    prompts_path = env("PLANK_PROMPTS", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deploy", "plank-prompts.txt"))
    os.makedirs(data_dir, exist_ok=True)
    prompts = load_prompts(prompts_path)
    judge = Judge(env("PLANK_MODEL", "claude-haiku-5-5"), int(env("PLANK_JUDGE_PER_DAY", "3000")))
    game = Plank(prompts, data_dir, judge, int(env("PLANK_SECONDS", "25")))
    print(f"plank: {len(prompts)} prompts, judge {'on' if judge.enabled else 'off'}, port {port}", flush=True)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(game))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main(sys.argv[1:])
