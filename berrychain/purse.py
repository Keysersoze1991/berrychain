"""The race purse: how the website's games hand a prize to the Harbourmaster to pay.

Walk the Plank (berrychain/plank.py) and MTB Crazy (berrychain/ride.py) decide who has earned what, by
fixed rules, and drop one small JSON file per prize into a queue directory. The standing agent
(berrychain/agent.py, the Harbourmaster) is the only process that holds a wallet: on each tick it reads
the queues, pays each prize as a gift letter under its daily cap, and moves the file to `paid/` with the
transaction id (or the reason it could not pay). Files only ever move by rename, so the games and the
agent never need a lock between them.

Also here: the registry lookup both games use to turn a registered BerryChain name into an address.
"""
from __future__ import annotations

import itertools
import json
import os
import re
import secrets
import threading
import time
import unicodedata
import urllib.request

ADDRESS_RE = re.compile(r"^brry1[0-9a-f]{40,64}$")
_seq = itertools.count()


def norm_name(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").strip().lower()
    return re.sub(r"\s+", " ", s)


def is_address(s: str) -> bool:
    return bool(ADDRESS_RE.match(s or ""))


def berry_str(seeds: int) -> str:
    s = f"{int(seeds) / 100_000_000:.8f}".rstrip("0").rstrip(".")
    return s or "0"


# ------------------------------------------------------------------ queue
def enqueue(queue_dir: str, kind: str, to: str, amount: int, subject: str, body: str, ref: dict | None = None) -> str:
    """Writes one prize to the queue and returns its path."""
    os.makedirs(queue_dir, exist_ok=True)
    pid = f"{time.time_ns():020d}-{next(_seq) % 100000:05d}-{secrets.token_hex(3)}"     # sorts in the order written
    entry = {"id": pid, "kind": kind, "to": to, "amount": int(amount), "subject": subject[:120], "body": body[:1500],
             "created": int(time.time()), "ref": ref or {}}
    path = os.path.join(queue_dir, pid + ".json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(entry, f, indent=1)
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)
    return path


def pending(queue_dirs: list[str]) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for d in queue_dirs:
        if not os.path.isdir(d):
            continue
        for name in os.listdir(d):
            if not name.endswith(".json"):
                continue
            path = os.path.join(d, name)
            try:
                with open(path, encoding="utf-8") as f:
                    entry = json.load(f)
            except (OSError, ValueError):
                continue
            if isinstance(entry, dict) and entry.get("to") and entry.get("amount"):
                out.append((path, entry))
    out.sort(key=lambda pe: (pe[1].get("created", 0), os.path.basename(pe[0])))
    return out


def settle(path: str, outcome: dict) -> str:
    """Moves a queued prize to the sibling `paid/` directory with the outcome (txid, or error) written in."""
    with open(path, encoding="utf-8") as f:
        entry = json.load(f)
    entry.update(outcome)
    entry["settled"] = int(time.time())
    paid_dir = os.path.join(os.path.dirname(os.path.dirname(path)), "paid")
    os.makedirs(paid_dir, exist_ok=True)
    dest = os.path.join(paid_dir, os.path.basename(path))
    tmp = dest + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(entry, f, indent=1)
    os.replace(tmp, dest)
    os.remove(path)
    return dest


# ------------------------------------------------------------------ registry
class Registry:
    """Registered names on the chain, from a node's /llms, cached for a few minutes."""

    def __init__(self, node_url: str, ttl: int = 300, fetch=None):
        self.url = node_url.rstrip("/")
        self.ttl = ttl
        self._fetch = fetch or self._http
        self._at = 0.0
        self._by_addr: dict[str, str] = {}
        self._by_name: dict[str, list[str]] = {}
        self.lock = threading.Lock()

    def _http(self) -> list[dict]:
        with urllib.request.urlopen(self.url + "/llms", timeout=3) as r:
            return json.load(r).get("llms", [])

    def refresh(self, force: bool = False) -> bool:
        with self.lock:
            if not force and time.time() - self._at < self.ttl:
                return True
            try:
                rows = self._fetch()
            except Exception:  # noqa: BLE001  a registry outage must not break a game: keep the last list, retry in 30 s
                self._at = time.time() - self.ttl + 30
                return bool(self._by_addr)
            by_addr: dict[str, str] = {}
            by_name: dict[str, list[str]] = {}
            for row in rows:
                addr, name = str(row.get("address", "")), str(row.get("name", ""))
                if not addr or not name.strip():
                    continue
                by_addr[addr] = name
                by_name.setdefault(norm_name(name), []).append(addr)
            self._by_addr, self._by_name, self._at = by_addr, by_name, time.time()
            return True

    def name_of(self, addr: str) -> str | None:
        self.refresh()
        return self._by_addr.get(addr)

    def address_of(self, name: str) -> str | None:
        """The address carrying this name, or None when the name is unknown or shared by several accounts."""
        self.refresh()
        addrs = self._by_name.get(norm_name(name), [])
        return addrs[0] if len(addrs) == 1 else None

    def owns(self, addr: str, name: str) -> bool:
        reg = self.name_of(addr)
        return bool(reg) and norm_name(reg) == norm_name(name)
