"""
BerryChain node: JSON-over-HTTP API, peer sync and an optional local miner.

    python -m berrychain.cli node --genesis genesis.json --data data/node1 --port 8801 \
        [--peer http://host:8802] [--mine brry1...] [--admin-token SECRET]

Every response is JSON. Errors are {"error": "..."} with a 4xx status.

Public endpoints are read-only plus /tx and /block submission. The admin
endpoints (/mine, /peers POST) need the X-Admin-Token header when a token is
configured; without a token they are only accepted from the loopback address.

Sync is headers-first and incremental: a node that is behind fetches the
peer's headers from the last common block, checks proof-of-work and total
work on the headers alone, and only then downloads block bodies in pages.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import params
from .chain import BlockError, Chain, header_of
from .state import TxError
from .tx import txid as _txid

SYNC_INTERVAL = 10          # seconds between peer polls
MAX_BODY_TX = params.MAX_TX_BYTES * 2
MAX_BODY_BLOCK = params.MAX_BLOCK_BYTES + 64 * 1024
MAX_BODY_SMALL = 4 * 1024


class Node:
    def __init__(self, chain: Chain, data_dir: str | None = None, peers: list[str] | None = None,
                 admin_token: str | None = None):
        self.chain = chain
        self.data_dir = data_dir
        self.self_url: str | None = None      # how peers can reach us
        self.announce = False                 # set when --advertise gives a reachable URL
        self.peers: list[str] = []
        for p in peers or []:
            self.add_peer(p)
        self.miner_addr: str | None = None
        self.admin_token = admin_token
        self._stop = threading.Event()
        self._sync_lock = threading.Lock()
        self.started = time.time()
        if data_dir:
            os.makedirs(data_dir, exist_ok=True)

    # --------------------------------------------------------- lifecycle
    @property
    def chain_path(self) -> str | None:
        return os.path.join(self.data_dir, "chain.json") if self.data_dir else None

    def persist(self) -> None:
        if self.chain_path:
            self.chain.save(self.chain_path)

    def start_background(self) -> None:
        # Announce ourselves only when we have a public URL. A home miner
        # behind NAT (no --advertise) still pushes blocks and polls peers, it
        # just does not ask them to connect back to an address they cannot reach.
        if self.self_url and self.announce:
            self._broadcast("/peers", {"url": self.self_url}, admin=True)
        threading.Thread(target=self._sync_loop, daemon=True).start()
        if self.miner_addr:
            threading.Thread(target=self._mine_loop, daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    # ------------------------------------------------------------ actions
    def submit_tx(self, tx: dict, gossip: bool = True) -> str:
        with self.chain.lock:
            tid = _txid(tx) if isinstance(tx, dict) else None
            known = tid in self.chain.mempool or tid in self.chain.tx_index
            tid = self.chain.add_tx(tx)
        if gossip and not known:
            self._broadcast("/tx", tx)
        return tid

    def accept_block(self, blk: dict, gossip: bool = True) -> bool:
        """Handle a block pushed by a peer. Returns True if it extended our chain."""
        if not isinstance(blk, dict) or not isinstance(blk.get("height"), int):
            raise BlockError("malformed block")
        with self.chain.lock:
            if blk["height"] <= self.chain.height:
                return False                                   # old or already known
            if blk["height"] == self.chain.height + 1 and blk.get("prev_hash") == self.chain.tip["hash"]:
                self.chain.add_block(blk)
            else:
                threading.Thread(target=self._sync_once, daemon=True).start()   # we are behind / forked
                return False
        self.persist()
        if gossip:
            self._broadcast("/block", blk)
        return True

    def mine(self, miner: str, count: int = 1) -> list[dict]:
        mined = []
        for _ in range(count):
            try:
                blk = self.chain.mine_block(miner, should_stop=self._stop.is_set)
            except BlockError as e:
                print(f"miner: block rejected: {e}", flush=True)
                continue                                       # tip moved while mining; retry
            if blk is None:
                break
            mined.append(blk)
            self.persist()
            self._broadcast("/block", blk)
        return mined

    def add_peer(self, url: str) -> bool:
        if not isinstance(url, str):
            return False
        url = url.strip().rstrip("/")
        u = urlparse(url)
        if u.scheme not in ("http", "https") or not u.netloc or u.path not in ("", "/") or u.query:
            return False
        if url == self.self_url or url in self.peers or len(self.peers) >= params.MAX_PEERS:
            return False
        self.peers.append(url)
        return True

    # ------------------------------------------------------------ network
    def _http(self, url: str, data: dict | None = None, timeout: float = 5.0, admin: bool = False, max_bytes: int = 64 * 1024 * 1024):
        body = json.dumps(data).encode() if data is not None else None
        headers = {"Content-Type": "application/json"}
        if admin and self.admin_token:
            headers["X-Admin-Token"] = self.admin_token
        req = urllib.request.Request(url, data=body, headers=headers, method="POST" if body else "GET")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(max_bytes + 1)
            if len(raw) > max_bytes:
                raise ValueError("peer response too large")
            return json.loads(raw.decode())

    def _broadcast(self, path: str, payload: dict, admin: bool = False) -> None:
        def go(peer):
            try:
                self._http(peer + path, payload, admin=admin)
            except Exception:  # noqa: BLE001
                pass
        for p in list(self.peers):
            threading.Thread(target=go, args=(p,), daemon=True).start()

    def _sync_from(self, peer: str) -> bool:
        """Headers-first incremental sync from one peer. Returns True if we adopted blocks."""
        st = self._http(peer + "/status")
        if st.get("chain_id") != self.chain.profile["chain_id"]:
            return False
        if st.get("work", 0) <= self.chain.cumulative_work():
            return False
        peer_height = int(st["height"])

        # 1. find the last common block by walking back in growing steps,
        #    always ending with a look at the genesis itself
        common = None
        step, h = 1, min(self.chain.height, peer_height)
        while True:
            hdrs = self._http(f"{peer}/headers?from={h}&to={h}")["headers"]
            if hdrs and hdrs[0]["hash"] == self.chain.blocks[h]["hash"]:
                common = h
                break
            if h == 0:
                break
            h, step = max(0, h - step), step * 2
        if common is None:
            return False                                       # different genesis

        # 2. fetch and verify headers beyond the common block
        headers = [header_of(b) for b in self.chain.blocks[:common + 1]]
        lo = common + 1
        while lo <= peer_height:
            hi = min(lo + params.MAX_HEADERS_PER_REQUEST - 1, peer_height)
            page = self._http(f"{peer}/headers?from={lo}&to={hi}")["headers"]
            if not page:
                break
            headers.extend(page)
            lo = hi + 1
        if self.chain.check_headers(headers) <= self.chain.cumulative_work():
            return False

        # 3. download bodies and apply
        if common == self.chain.height:
            # fast path: peer simply extends us, apply page by page
            lo = common + 1
            while lo <= peer_height:
                hi = min(lo + params.MAX_BLOCKS_PER_REQUEST - 1, peer_height)
                for b in self._http(f"{peer}/blocks?from={lo}&to={hi}", timeout=60)["blocks"]:
                    self.chain.add_block(b)
                lo = hi + 1
        else:
            # fork: assemble the candidate chain and let fork choice decide
            blocks = list(self.chain.blocks[:common + 1])
            lo = common + 1
            while lo <= peer_height:
                hi = min(lo + params.MAX_BLOCKS_PER_REQUEST - 1, peer_height)
                blocks.extend(self._http(f"{peer}/blocks?from={lo}&to={hi}", timeout=60)["blocks"])
                lo = hi + 1
            if not self.chain.replace_with(blocks):
                return False
        self.persist()
        for p in st.get("peers", []):
            self.add_peer(p)
        return True

    def _sync_once(self) -> None:
        if not self._sync_lock.acquire(blocking=False):
            return
        try:
            for peer in list(self.peers):
                try:
                    self._sync_from(peer)
                except (urllib.error.URLError, BlockError, TxError, KeyError, ValueError, TypeError, OSError):
                    continue
        finally:
            self._sync_lock.release()

    def _sync_loop(self) -> None:
        while not self._stop.is_set():
            self._sync_once()
            self._stop.wait(SYNC_INTERVAL)

    def _mine_loop(self) -> None:
        misses = 0
        while not self._stop.is_set():
            try:
                blk = self.chain.mine_block(self.miner_addr, max_iters=200_000, should_stop=self._stop.is_set)
            except BlockError as e:
                print(f"miner: block rejected: {e}", flush=True)   # tip moved or clock trouble; retry
                continue
            if blk is None:
                misses += 1
                if misses % 50 == 0:
                    print(f"miner: {misses} rounds without a block at height {self.chain.height + 1}", flush=True)
                continue
            misses = 0
            self.persist()
            self._broadcast("/block", blk)

    # -------------------------------------------------------------- views
    def status(self) -> dict:
        c = self.chain
        return {
            "chain_id": c.profile["chain_id"],
            "profile": c.profile_name,
            "height": c.height,
            "tip_hash": c.tip["hash"],
            "tip_time": c.tip["timestamp"],
            "next_target": f"{c.target_for_height(c.height + 1):064x}",
            "work": c.cumulative_work(),
            "mempool": len(c.mempool),
            "peers": self.peers,
            "uptime": int(time.time() - self.started),
            "supply": c.supply(),
        }


def make_handler(node: Node):
    class Handler(BaseHTTPRequestHandler):
        server_version = "BerryChain/0.2"

        def log_message(self, fmt, *args):  # quiet
            pass

        def _send(self, obj, status=200):
            body = json.dumps(obj).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def _error(self, msg, status=400):
            self._send({"error": str(msg)}, status)

        def _body(self, limit: int):
            n = int(self.headers.get("Content-Length") or 0)
            if n > limit:
                raise ValueError("request body too large")
            return json.loads(self.rfile.read(n).decode() or "null")

        def _is_admin(self) -> bool:
            if node.admin_token:
                return secrets.compare_digest(self.headers.get("X-Admin-Token", ""), node.admin_token)
            return self.client_address[0] in ("127.0.0.1", "::1")

        def do_GET(self):
            try:
                self._route_get()
            except (ValueError, KeyError) as e:
                self._error(e, 400)
            except Exception as e:  # noqa: BLE001
                self._error(f"{type(e).__name__}: {e}", 500)

        def do_POST(self):
            try:
                self._route_post()
            except (TxError, BlockError, ValueError, KeyError, TypeError) as e:
                self._error(e, 400)
            except Exception as e:  # noqa: BLE001
                self._error(f"{type(e).__name__}: {e}", 500)

        # ------------------------------------------------------------ GET
        def _route_get(self):
            u = urlparse(self.path)
            parts = [p for p in u.path.split("/") if p]
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            c, st = node.chain, node.chain.state
            head = parts[0] if parts else ""
            arg = parts[1] if len(parts) > 1 else None

            if head == "" or head == "status":
                return self._send(node.status())
            if head == "supply":
                return self._send(c.supply())
            if head == "params":
                return self._send({"profile": c.profile, "seeds_per_berry": params.SEEDS_PER_BERRY,
                                   "min_fee": params.MIN_FEE, "grant_tiers": params.GRANT_TIERS,
                                   "treasury": params.TREASURY_ADDRESS, "founding_pool": params.FOUNDING_POOL_ADDRESS,
                                   "founding_slots": params.FOUNDING_LLM_SLOTS, "founding_grant": params.ALLOC_FOUNDING_LLM_EACH,
                                   "max_inline_bytes": params.MAX_PACKET_INLINE_BYTES})
            if head == "balance" and arg:
                return self._send({"address": arg, "balance": st.balance(arg), "nonce": st.nonce(arg),
                                   "next_nonce": st.nonce(arg) + sum(1 for t in c.mempool.values() if t.get("from") == arg)})
            if head == "account" and arg:
                return self._send({"address": arg, "balance": st.balance(arg), "nonce": st.nonce(arg),
                                   "next_nonce": st.nonce(arg) + sum(1 for t in c.mempool.values() if t.get("from") == arg),
                                   "llm": st.llms.get(arg), "reputation": st.reputation.get(arg),
                                   "is_registrar": arg in st.registrars})
            if head == "block" and arg:
                if arg.isdigit():
                    h = int(arg)
                    if h > c.height:
                        return self._error("no such block", 404)
                    return self._send(c.blocks[h])
                for b in reversed(c.blocks):
                    if b["hash"] == arg:
                        return self._send(b)
                return self._error("no such block", 404)
            if head == "blocks":
                lo = max(0, int(q.get("from", max(0, c.height - 20))))
                hi = min(int(q.get("to", c.height)), lo + params.MAX_BLOCKS_PER_REQUEST - 1, c.height)
                return self._send({"blocks": c.blocks[lo:hi + 1]})
            if head == "headers":
                lo = max(0, int(q.get("from", 0)))
                hi = min(int(q.get("to", c.height)), lo + params.MAX_HEADERS_PER_REQUEST - 1, c.height)
                return self._send({"headers": c.headers(lo, hi), "height": c.height})
            if head == "tx" and arg:
                r = c.get_tx(arg)
                return self._send(r) if r else self._error("unknown txid", 404)
            if head == "mempool":
                return self._send({"txs": list(c.mempool.values())})
            if head == "packets":
                items = list(st.packets.values())
                if q.get("seller"):
                    items = [p for p in items if p["seller"] == q["seller"]]
                if q.get("tag"):
                    items = [p for p in items if q["tag"] in p["tags"]]
                if q.get("active", "1") == "1":
                    items = [p for p in items if p["active"]]
                return self._send({"packets": items})
            if head == "packet" and arg:
                p = st.packets.get(arg)
                if not p:
                    return self._error("no such packet", 404)
                p = dict(p)
                p["ciphertext"] = c.get_ciphertext(arg) if p["inline"] else None
                p["seller_reputation"] = st.reputation.get(p["seller"])
                return self._send(p)
            if head == "escrow" and arg:
                e = st.escrows.get(arg)
                return self._send(e) if e else self._error("no such escrow", 404)
            if head == "escrows":
                items = list(st.escrows.values())
                for k in ("buyer", "seller", "status", "packet_id"):
                    if q.get(k):
                        items = [e for e in items if e[k] == q[k]]
                return self._send({"escrows": items})
            if head == "llms":
                return self._send({"llms": [{"address": a, **r, "reputation": st.reputation.get(a)} for a, r in st.llms.items()]})
            if head == "llm" and arg:
                r = st.llms.get(arg)
                return self._send({"address": arg, **r, "reputation": st.reputation.get(arg)}) if r else self._error("not a registered LLM", 404)
            if head == "registrars":
                return self._send({"registrars": st.registrars, "threshold": st.registrar_threshold,
                                   "treasury": params.TREASURY_ADDRESS, "treasury_balance": st.balance(params.TREASURY_ADDRESS),
                                   "founding_pool": params.FOUNDING_POOL_ADDRESS, "founding_pool_balance": st.balance(params.FOUNDING_POOL_ADDRESS)})
            if head == "grants":
                nxt = c.height + 1
                return self._send({"grants": st.grants, "tiers": params.GRANT_TIERS,
                                   "issued": st.grant_counts, "halving_every": params.GRANT_HALVING_EVERY,
                                   "current_amounts": {t: st.grant_amount(t, nxt) for t in params.GRANT_TIERS}})
            if head == "founders":
                return self._send({"founders": st.founders, "slots": params.FOUNDING_LLM_SLOTS,
                                   "slots_remaining": params.FOUNDING_LLM_SLOTS - len(st.founders),
                                   "pool_remaining": st.balance(params.FOUNDING_POOL_ADDRESS)})
            if head == "gifts":
                return self._send({"gifts": st.gifts})
            if head == "peers":
                return self._send({"peers": node.peers})
            return self._error("not found", 404)

        # ----------------------------------------------------------- POST
        def _route_post(self):
            parts = [p for p in urlparse(self.path).path.split("/") if p]
            head = parts[0] if parts else ""
            if head == "tx":
                body = self._body(MAX_BODY_TX)
                return self._send({"txid": node.submit_tx(body), "status": "pending"})
            if head == "block":
                body = self._body(MAX_BODY_BLOCK)
                return self._send({"accepted": node.accept_block(body), "height": node.chain.height})
            if head == "peers":
                # peer announcements are part of the protocol, so this is open;
                # add_peer validates the URL and caps the list
                body = self._body(MAX_BODY_SMALL)
                added = node.add_peer(body.get("url") if isinstance(body, dict) else None)
                return self._send({"added": added, "peers": node.peers})
            if head == "mine":
                if not self._is_admin():
                    return self._error("admin token required", 403)
                body = self._body(MAX_BODY_SMALL) or {}
                miner = body.get("miner") or node.miner_addr
                if not miner:
                    raise ValueError("miner address required")
                count = max(1, min(int(body.get("blocks", 1)), 50))
                blocks = node.mine(miner, count)
                return self._send({"mined": [{"height": b["height"], "hash": b["hash"], "txs": len(b["txs"])} for b in blocks],
                                   "height": node.chain.height})
            return self._error("not found", 404)

    return Handler


def serve(node: Node, host: str = "127.0.0.1", port: int = 8801, advertise: str | None = None) -> None:
    server = ThreadingHTTPServer((host, port), make_handler(node))
    server.daemon_threads = True
    node.self_url = (advertise or f"http://{host}:{port}").rstrip("/")
    node.announce = advertise is not None
    node.start_background()
    print(f"BerryChain node on http://{host}:{port}  chain={node.chain.profile['chain_id']} height={node.chain.height}"
          + ("" if node.admin_token else "  (admin endpoints: loopback only)"))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        node.stop()
        node.persist()
        server.server_close()


def open_or_create(genesis_path: str, data_dir: str | None) -> Chain:
    """Load the persisted chain if it belongs to the genesis we were given;
    otherwise set the stale file aside and start from that genesis. A node
    must never silently keep mining a retired chain."""
    fresh = Chain.from_genesis_file(genesis_path)
    path = os.path.join(data_dir, "chain.json") if data_dir else None
    if path and os.path.exists(path):
        stored = Chain.load(path)
        if stored.blocks[0]["hash"] == fresh.blocks[0]["hash"]:
            return stored
        old = stored.blocks[0]["hash"][:8]
        aside = os.path.join(data_dir, f"chain-stale-{old}.json")
        os.replace(path, aside)
        print(f"stored chain has genesis {old}..., not the genesis in {genesis_path}; "
              f"moved it to {aside} and starting from the given genesis", flush=True)
    return fresh
