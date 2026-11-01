"""MTB Crazy: the record board and the referee (see docs/RIDE.md).

Every run in the browser is recorded as an input log, one mask per tick. A player who beats the record
on a course sends the log here; the referee replays it on the very same engine the page runs
(site/ride/engine.js under Node, through site/ride/check.js) and the clock the replay shows is the only
time that counts. One record per course. When a record changes hands the new holder's prize is dropped
in the race purse queue for the Harbourmaster to pay (berrychain/purse.py): 0.2 BERRY, or 2 BERRY when
the record was set under the holder's own registered BerryChain name.

Small stand-alone HTTP service, fronted by nginx at /ride/ like Walk the Plank. State is one JSON file.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from . import params, purse

COURSES = 20
MAX_NAME = 24
MAX_LOG = 24000                     # ticks, as in engine.js
LOG_RE = re.compile(r"^[0-9a-v]+$")
HISTORY = 500
ORIGINS = {"https://berrychain.link", "https://www.berrychain.link", "http://localhost:8765", "http://127.0.0.1:8765"}


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def today() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")


def clean_name(s: str) -> str:
    return re.sub(r"[^\w .'-]", "", str(s or ""))[:MAX_NAME].strip()


# ------------------------------------------------------------------ referee
class RefereeDown(Exception):
    pass


class Referee:
    """Replays a run with Node on the shared engine. One replay at a time; a few hundred ms each."""

    def __init__(self, node: str, check_js: str, seconds: int = 20):
        self.node, self.check, self.seconds = node, check_js, seconds
        self.lock = threading.Lock()

    def _run(self, args: list[str], stdin: str | None) -> dict | list:
        try:
            p = subprocess.run([self.node, self.check, *args], input=stdin, capture_output=True, text=True, timeout=self.seconds)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise RefereeDown(str(e)) from e
        out = (p.stdout or "").strip().splitlines()
        if not out:
            raise RefereeDown((p.stderr or "no output")[-300:])
        try:
            return json.loads(out[-1])
        except ValueError as e:
            raise RefereeDown("bad referee output") from e

    def courses(self) -> list[dict]:
        rows = self._run(["--courses"], None)
        if not isinstance(rows, list) or len(rows) != COURSES:
            raise RefereeDown("course list")
        return rows

    def replay(self, level: int, log: str) -> dict | None:
        with self.lock:
            res = self._run([], json.dumps({"level": level, "log": log}))
        if not isinstance(res, dict) or res.get("error"):
            raise RefereeDown(str(res.get("error") if isinstance(res, dict) else res))
        return res if res.get("finished") else None


# ------------------------------------------------------------------ board
class Board:
    def __init__(self, data_dir: str, courses: list[dict], referee: Referee, registry: purse.Registry):
        self.dir = data_dir
        self.path = os.path.join(data_dir, "ride-state.json")
        self.queue = os.path.join(data_dir, "queue")
        self.courses = courses
        self.referee = referee
        self.registry = registry
        self.lock = threading.Lock()
        self.state: dict[str, Any] = {"records": {}, "paid": {}, "history": []}
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as f:
                self.state.update(json.load(f))
        self._minute, self._claims = 0, 0

    def save(self) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.state, f, separators=(",", ":"))
        os.replace(tmp, self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    @staticmethod
    def _public(level: int, rec: dict | None) -> dict:
        if not rec:
            return {"level": level}
        return {"level": level, "name": rec["name"], "time": rec["time"], "named": bool(rec.get("named")),
                "day": rec["day"], "tricks": rec.get("tricks", 0), "crashes": rec.get("crashes", 0)}

    def view(self) -> list[dict]:
        out = []
        for i, c in enumerate(self.courses):
            row = self._public(i, self.state["records"].get(str(i)))
            row.update({"course": c["name"], "tier": c["tier"]})
            out.append(row)
        return out

    def claim(self, level: int, name: str, addr: str, log: str) -> tuple[dict, int]:
        """-> (response, http status). Replays first; nothing is taken on the player's word."""
        if not 0 <= level < COURSES:
            return {"error": "no such course"}, 400
        name = clean_name(name)
        if not name:
            return {"error": "a record needs a name"}, 400
        addr = (addr or "").strip()
        if addr and not purse.is_address(addr):
            return {"error": "that is not a BerryChain address"}, 400
        if not log or len(log) > MAX_LOG or not LOG_RE.match(log):
            return {"error": "bad run log"}, 400
        minute = int(time.time() // 60)
        if minute != self._minute:
            self._minute, self._claims = minute, 0
        self._claims += 1
        if self._claims > 60:
            return {"error": "the referee is busy; try again in a minute"}, 429
        try:
            res = self.referee.replay(level, log)
        except RefereeDown as e:
            print(f"ride: referee down: {e}", flush=True)
            return {"error": "the referee is away; your run was not judged"}, 503
        if res is None:
            return {"error": "that run never reached the flag"}, 400
        t = int(res["time"])
        course = self.courses[level]
        key = str(level)
        rec = self.state["records"].get(key)
        if rec and t >= rec["time"]:
            return {"record": False, "time": t, "holder": self._public(level, rec),
                    "why": f"The record on {course['name']} stands at {rec['time'] / 60:.2f} s."}, 200
        # who gets the coins
        named = False
        if addr:
            named = self.registry.owns(addr, name)
        else:
            found = self.registry.address_of(name)
            if found:
                addr, named = found, True
        amount = params.PURSE_RIDE_NAMED if named else params.PURSE_RIDE_RECORD if addr else 0
        day = today()
        why = ""
        if not addr:
            amount, why = 0, "No address given, so the purse stays on the table. Give one next time and the coins come to you."
        elif rec and rec.get("addr") == addr:
            amount, why = 0, "You already held this course; the purse only moves when the record changes hands."
        elif self.state["paid"].get(key) == day:
            amount, why = 0, "This course has paid out once today already; the purse opens again tomorrow (UTC)."
        new = {"name": name, "addr": addr, "named": named, "time": t, "raw": int(res.get("raw", t)), "bonus": int(res.get("bonus", 0)),
               "tricks": int(res.get("tricks", 0)), "crashes": int(res.get("crashes", 0)), "ticks": len(log), "log": log,
               "day": day, "at": int(time.time()), "purse": amount}
        if amount:
            subject = f"MTB Crazy: the record on {course['name']} is yours"
            body = (f"You set the record on {course['name']} ({course['tier']}): {t / 60:.2f} s"
                    + (f", {new['tricks']} trick{'s' if new['tricks'] != 1 else ''}" if new["tricks"] else "")
                    + (f", {new['crashes']} crash{'es' if new['crashes'] != 1 else ''}" if new["crashes"] else ", not a scratch on you")
                    + (f", beating {rec['name']} at {rec['time'] / 60:.2f} s" if rec else "")
                    + f". The purse for that course rides with this letter: {purse.berry_str(amount)} BERRY"
                    + (", the full purse, because you rode under your own registered name" if named else
                       "; set it under your registered BerryChain name and it is 2 BERRY next time")
                    + ". Hold the record as long as you can; when someone takes it, the purse goes to them. "
                      "BERRY has no price and no value; it is the coin you write letters with.")
            purse.enqueue(self.queue, "ride-record", addr, amount, subject, body,
                          ref={"level": level, "course": course["name"], "time": t, "name": name, "named": named})
            self.state["paid"][key] = day
            why = f"{purse.berry_str(amount)} BERRY is on its way to your chest as a letter from the Harbourmaster."
        self.state["records"][key] = new
        self.state.setdefault("history", []).append({k: new[k] for k in ("name", "time", "day", "named", "purse")} | {"level": level, "addr": addr[:12]})
        self.state["history"] = self.state["history"][-HISTORY:]
        beaten = self._public(level, rec) if rec else None
        return {"record": True, "time": t, "named": named, "purse": purse.berry_str(amount) if amount else None, "why": why,
                "beaten": beaten, "board": self.view()}, 200


# ------------------------------------------------------------------ http
def make_handler(board: Board):
    class Handler(BaseHTTPRequestHandler):
        server_version = "BerryChainRide/1"

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

        def do_GET(self):
            route = self.path.split("?")[0]
            with board.lock:
                if route == "/ride/status":
                    held = sum(1 for r in board.state["records"].values() if r)
                    return self._send({"courses": COURSES, "records": held, "day": today(),
                                       "purse": {"record": purse.berry_str(params.PURSE_RIDE_RECORD), "named": purse.berry_str(params.PURSE_RIDE_NAMED)}})
                if route == "/ride/board":
                    return self._send({"board": board.view(), "day": today()})
            return self._send({"error": "not found"}, 404)

        def do_POST(self):
            route = self.path.split("?")[0]
            if route != "/ride/claim":
                return self._send({"error": "not found"}, 404)
            try:
                n = int(self.headers.get("Content-Length", "0"))
                if n > 64 * 1024:
                    return self._send({"error": "too large"}, 413)
                body = json.loads(self.rfile.read(n) or b"{}")
            except Exception:
                return self._send({"error": "bad json"}, 400)
            try:
                level = int(body.get("level", -1))
            except (TypeError, ValueError):
                level = -1
            with board.lock:
                res, status = board.claim(level, str(body.get("name", "")), str(body.get("addr", "")), str(body.get("log", "")))
                if status == 200:
                    board.save()
            return self._send(res, status)

    return Handler


def main(argv=None) -> None:
    port = int(env("RIDE_PORT", "8806"))
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = env("RIDE_DIR") or ("/var/lib/berrychain/ride" if os.name != "nt" else os.path.join(os.environ.get("TEMP", "."), "berrychain-ride"))
    os.makedirs(data_dir, exist_ok=True)
    referee = Referee(env("RIDE_NODE", "node"), env("RIDE_CHECK", os.path.join(root, "site", "ride", "check.js")), int(env("RIDE_REPLAY_SECONDS", "20")))
    try:
        courses = referee.courses()
    except RefereeDown as e:
        raise SystemExit(f"ride: the referee (node + site/ride/check.js) does not run: {e}")
    registry = purse.Registry(env("RIDE_NODE_URL", "http://127.0.0.1:8801"))
    board = Board(data_dir, courses, referee, registry)
    print(f"ride: {len(courses)} courses, {len(board.state['records'])} records held, port {port}", flush=True)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(board))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main(sys.argv[1:])
