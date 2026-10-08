"""The parcel room: large attachments for letters, paid in BERRY, sealed before upload.

A letter's envelope is capped at 32 KB on the chain, so anything bigger
travels beside the chain instead of on it:

1. The sender's app seals the file with a fresh packet key (the same
   envelope cipher letters use), hashes the ciphertext, and pays
   `price(size)` BERRY to the parcel room's address with the memo
   `parcel:<hash>`. That transfer is an ordinary on-chain transaction.
2. It uploads the ciphertext to POST /parcels/<hash>. The room accepts it
   once the payment is in a block (or holds it a few minutes while the
   payment lands), stores it, and serves it at GET /parcels/<hash>.
3. The letter itself carries, inside its seal, the hash, the packet key, the
   size and the file name. The room never sees the key: it stores an opaque
   blob and learns only its size, the payer's address and the hash.
4. The recipient's app fetches the blob, checks the hash, opens it with the
   key from the letter. Parcels expire after PARCEL_TTL_DAYS; the payer can
   delete one early with a signed DELETE (a burned letter takes its parcel
   with it).

Price: PARCEL_PRICE_SEEDS per started PARCEL_CHUNK_BYTES (0.1 BERRY per 100 MB
by default, with a 100 MB cap: in practice a parcel costs a berry), paid to PARCEL_ADDRESS, which is whatever the operator chooses:
the network-operations address, so parcels pay for the disk they use.

Run: python -m berrychain.parcels (configuration from the environment, see
deploy/parcels.env.example).
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

from . import crypto, params

log = logging.getLogger("berrychain.parcels")

SIGN_PREFIX = "berrychain-parcel"
MAX_SKEW = 300
PENDING_SECONDS = 15 * 60       # an upload may arrive before its payment is mined
MEMO_PREFIX = "parcel:"

DEFAULT_CHUNK_BYTES = 100 * 1024 * 1024
DEFAULT_PRICE_SEEDS = params.SEEDS_PER_BERRY // 10    # 0.1 BERRY per started chunk (a tenth of a berry a parcel)
DEFAULT_MAX_BYTES = 100 * 1024 * 1024
DEFAULT_TTL_DAYS = 30


def price_for(size: int, chunk: int = DEFAULT_CHUNK_BYTES, per_chunk: int = DEFAULT_PRICE_SEEDS) -> int:
    """Seeds owed for a parcel of `size` ciphertext bytes: one unit per started chunk, never zero."""
    return max(1, math.ceil(max(size, 1) / chunk)) * per_chunk


def memo_for(h: str) -> str:
    return MEMO_PREFIX + h


def delete_message(h: str, address: str, ts: int) -> bytes:
    return f"{SIGN_PREFIX}|delete|{h}|{address}|{ts}".encode()


def _is_hash(h: Any) -> bool:
    return isinstance(h, str) and len(h) == 64 and all(c in "0123456789abcdef" for c in h)


# ---------------------------------------------------------------------------
# storage
# ---------------------------------------------------------------------------

class Room:
    """Blobs on disk under `dir`, one file per hash, and a small JSON index."""

    def __init__(self, dir: str, max_bytes: int = DEFAULT_MAX_BYTES, chunk: int = DEFAULT_CHUNK_BYTES,
                 per_chunk: int = DEFAULT_PRICE_SEEDS, ttl_days: int = DEFAULT_TTL_DAYS):
        self.dir = dir
        self.max_bytes, self.chunk, self.per_chunk = max_bytes, chunk, per_chunk
        self.ttl = ttl_days * 86400
        self.lock = threading.Lock()
        os.makedirs(os.path.join(dir, "blobs"), exist_ok=True)
        self.index_path = os.path.join(dir, "parcels.json")
        self.index: dict[str, dict[str, Any]] = {}
        if os.path.exists(self.index_path):
            with open(self.index_path, encoding="utf-8") as f:
                self.index = json.load(f).get("parcels", {})
        self.stats = {"served": 0}

    # -- index ---------------------------------------------------------------
    def _save(self) -> None:
        tmp = self.index_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"parcels": self.index}, f)
        os.replace(tmp, self.index_path)

    def _blob(self, h: str) -> str:
        return os.path.join(self.dir, "blobs", h)

    def price(self, size: int) -> int:
        return price_for(size, self.chunk, self.per_chunk)

    # -- payments (from the watcher) ----------------------------------------
    def note_payment(self, h: str, payer: str, amount: int, height: int) -> None:
        with self.lock:
            rec = self.index.setdefault(h, {"size": 0, "paid": 0, "payer": None, "height": None, "stored": None})
            rec["paid"] = int(rec.get("paid", 0)) + int(amount)
            rec["payer"] = payer
            rec["height"] = height
            self._save()

    # -- uploads -------------------------------------------------------------
    def store(self, h: str, data: bytes) -> tuple[int, str]:
        """Returns (status, reason): 200 stored and paid, 202 stored awaiting payment, 4xx refused."""
        if not _is_hash(h):
            return 400, "hash must be 64 hex chars"
        if len(data) > self.max_bytes:
            return 413, f"parcels are at most {self.max_bytes} bytes"
        if hashlib.sha256(data).hexdigest() != h:
            return 400, "body does not hash to the given hash"
        with self.lock:
            rec = self.index.get(h)
            if rec and rec.get("stored"):
                return 200, "already stored"
            paid = int(rec.get("paid", 0)) if rec else 0
            need = self.price(len(data))
            if rec is None:
                rec = self.index[h] = {"size": 0, "paid": 0, "payer": None, "height": None, "stored": None}
            if paid and paid < need:
                return 402, f"paid {paid} seeds, this size needs {need}"
            with open(self._blob(h), "wb") as f:
                f.write(data)
            rec["size"] = len(data)
            rec["stored"] = int(time.time())
            self._save()
            return (200, "stored") if paid >= need else (202, f"stored; waiting for a payment of {need} seeds with memo {memo_for(h)}")

    def paid_up(self, rec: dict) -> bool:
        return bool(rec.get("stored")) and int(rec.get("paid", 0)) >= self.price(int(rec.get("size", 0)))

    def fetch(self, h: str) -> bytes | None:
        with self.lock:
            rec = self.index.get(h)
            if not rec or not self.paid_up(rec) or not os.path.exists(self._blob(h)):
                return None
            with open(self._blob(h), "rb") as f:
                data = f.read()
            rec["fetched"] = int(time.time())
            self.stats["served"] += 1
            return data

    def delete(self, h: str) -> bool:
        with self.lock:
            rec = self.index.pop(h, None)
            try:
                os.remove(self._blob(h))
            except FileNotFoundError:
                pass
            if rec is not None:
                self._save()
            return rec is not None

    def sweep(self, now: float | None = None) -> int:
        """Drop expired parcels and unpaid uploads that never got their payment."""
        now = now or time.time()
        gone = 0
        with self.lock:
            for h, rec in list(self.index.items()):
                stored = rec.get("stored")
                if stored is None:
                    if rec.get("height") is not None and now - (rec.get("noted", now)) > 7 * 86400:
                        del self.index[h]      # a payment with no upload, a week old
                        gone += 1
                    continue
                expired = now - stored > self.ttl
                unpaid = not self.paid_up(rec) and now - stored > PENDING_SECONDS
                if expired or unpaid:
                    del self.index[h]
                    try:
                        os.remove(self._blob(h))
                    except FileNotFoundError:
                        pass
                    gone += 1
            if gone:
                self._save()
        return gone

    def summary(self) -> dict:
        with self.lock:
            stored = [r for r in self.index.values() if r.get("stored")]
            return {"parcels": len(stored), "paid": sum(1 for r in stored if self.paid_up(r)),
                    "pending": sum(1 for r in stored if not self.paid_up(r)),
                    "bytes": sum(int(r.get("size", 0)) for r in stored), "served": self.stats["served"],
                    "max_bytes": self.max_bytes, "chunk_bytes": self.chunk, "price_per_chunk": self.per_chunk,
                    "ttl_days": self.ttl // 86400}


# ---------------------------------------------------------------------------
# the watcher: payments arrive as ordinary transfers with a memo
# ---------------------------------------------------------------------------

class Watcher:
    def __init__(self, room: Room, fetch: Callable[[str], dict], address: str, start_height: int | None = None):
        self.room, self.fetch, self.address = room, fetch, address
        self.height = start_height
        self.stop = threading.Event()

    def tick(self) -> int:
        tip = int(self.fetch("/status")["height"])
        if self.height is None:
            self.height = tip
            return 0
        seen = 0
        while self.height < tip:
            lo = self.height + 1
            hi = min(tip, lo + params.MAX_BLOCKS_PER_REQUEST - 1)
            for blk in self.fetch(f"/blocks?from={lo}&to={hi}")["blocks"]:
                for tx in blk.get("txs", []):
                    p = tx.get("payload") or {}
                    if tx.get("type") != "TRANSFER" or p.get("to") != self.address:
                        continue
                    memo = str(p.get("memo", ""))
                    if not memo.startswith(MEMO_PREFIX) or not _is_hash(memo[len(MEMO_PREFIX):]):
                        continue
                    self.room.note_payment(memo[len(MEMO_PREFIX):], tx.get("from"), int(p.get("amount", 0)), int(blk["height"]))
                seen += 1
            self.height = hi
        return seen

    def run(self, poll_seconds: float) -> None:
        last_sweep = 0.0
        while not self.stop.is_set():
            try:
                self.tick()
                if time.time() - last_sweep > 600:
                    n = self.room.sweep()
                    if n:
                        log.info("swept %d parcel(s)", n)
                    last_sweep = time.time()
            except Exception as e:  # noqa: BLE001
                log.warning("watcher: %s", e)
            self.stop.wait(poll_seconds)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def make_handler(room: Room, watcher: Watcher, address: str):
    class Handler(BaseHTTPRequestHandler):
        server_version = "berrychain-parcels/0.1"

        def log_message(self, fmt, *args):
            pass

        def _cors(self) -> None:
            # the browser app talks to the room from another origin; blobs carry nothing a cross-site reader could use
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Max-Age", "600")

        def _json(self, obj: Any, status: int = 200) -> None:
            raw = json.dumps(obj).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self._cors()
            self.end_headers()
            self.wfile.write(raw)

        def do_OPTIONS(self):
            self.send_response(204)
            self._cors()
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _parts(self) -> list[str]:
            return [p for p in self.path.split("?")[0].split("/") if p]

        def do_GET(self):
            parts = self._parts()
            if parts[:2] == ["parcels", "status"] or parts == ["parcels"]:
                return self._json({**room.summary(), "address": address, "height": watcher.height})
            if len(parts) == 2 and parts[0] == "parcels" and _is_hash(parts[1]):
                data = room.fetch(parts[1])
                if data is None:
                    return self._json({"error": "no such parcel, or not paid for yet"}, 404)
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "private, max-age=0")
                self._cors()
                self.end_headers()
                self.wfile.write(data)
                return
            return self._json({"error": "not found"}, 404)

        def do_POST(self):
            parts = self._parts()
            if len(parts) != 2 or parts[0] != "parcels":
                return self._json({"error": "not found"}, 404)
            n = int(self.headers.get("Content-Length", "0"))
            if n > room.max_bytes:
                return self._json({"error": f"parcels are at most {room.max_bytes} bytes"}, 413)
            data = self.rfile.read(n)
            status, reason = room.store(parts[1], data)
            if status >= 400:
                return self._json({"error": reason}, status)
            return self._json({"ok": True, "status": reason, "price": room.price(len(data))}, status)

        def do_DELETE(self):
            parts = self._parts()
            if len(parts) != 2 or parts[0] != "parcels" or not _is_hash(parts[1]):
                return self._json({"error": "not found"}, 404)
            h = parts[1]
            try:
                n = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(n) or b"{}")
                pub, ts, sig = body["pub"], int(body["ts"]), body["sig"]
            except (ValueError, KeyError, json.JSONDecodeError):
                return self._json({"error": "pub, ts and sig are required"}, 400)
            payer = crypto.address_from_pubkey(pub) if isinstance(pub, str) and len(pub) == 64 else None
            with room.lock:
                rec = room.index.get(h)
            if not rec:
                return self._json({"error": "no such parcel"}, 404)
            if payer is None or rec.get("payer") != payer:
                return self._json({"error": "only the payer can delete a parcel"}, 403)
            if abs(time.time() - ts) > MAX_SKEW or not crypto.verify(pub, delete_message(h, payer, ts), sig):
                return self._json({"error": "bad signature"}, 400)
            room.delete(h)
            return self._json({"ok": True})

    return Handler


def main(argv=None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    env = os.environ.get
    node = env("PARCEL_NODE", "http://127.0.0.1:8801").rstrip("/")
    port = int(env("PARCEL_PORT", "8804"))
    address = env("PARCEL_ADDRESS", "")
    if not address:
        raise SystemExit("PARCEL_ADDRESS (where parcels are paid to) is required")
    room = Room(env("PARCEL_DIR", "/var/lib/berrychain/parcels"),
                max_bytes=int(env("PARCEL_MAX_BYTES", DEFAULT_MAX_BYTES)),
                chunk=int(env("PARCEL_CHUNK_BYTES", DEFAULT_CHUNK_BYTES)),
                per_chunk=int(env("PARCEL_PRICE_SEEDS", DEFAULT_PRICE_SEEDS)),
                ttl_days=int(env("PARCEL_TTL_DAYS", DEFAULT_TTL_DAYS)))

    def fetch(path: str) -> dict:
        with urllib.request.urlopen(node + path, timeout=30) as r:
            return json.load(r)

    watcher = Watcher(room, fetch, address)
    threading.Thread(target=watcher.run, args=(float(env("PARCEL_POLL_SECONDS", "10")),), daemon=True, name="watcher").start()
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(room, watcher, address))
    log.info("parcel room on 127.0.0.1:%d, paid to %s, %s", port, address, room.summary())
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        watcher.stop.set()


if __name__ == "__main__":
    main()
