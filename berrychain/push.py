"""Opt-in push relay: a nudge the moment a sealed letter lands.

The phone app's own background check is at the mercy of the operating
system (iOS in particular runs it rarely, and never for an app the user has
swiped away). This small service fixes that for people who choose it:

* The app registers its push token together with the address it wants
  watched, signed by that address's key (POST /push/register). The relay
  keeps only that pairing, plus the height it started watching from.
* A watcher follows the local node block by block. Whenever a SEND_LETTER
  reaches a registered address it sends an Apple push that says a letter
  has arrived, and nothing else: no sender, no content, no amount.
* Unregistering (POST /push/unregister, also signed) forgets the pairing at
  once, as does a token Apple reports dead.

This is the one place in BerryChain where a server of ours learns which
device belongs to which address, which is why it is opt-in and why the
file holds nothing beyond that pairing.

Run:  python -m berrychain.push   (configuration from the environment, see
deploy/push.env.example).  Only Apple's APNs is implemented; Android's own
scheduler runs the app's background check reliably enough.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

from . import crypto

log = logging.getLogger("berrychain.push")

SIGN_PREFIX = "berrychain-push"
MAX_SKEW = 300          # seconds a registration's timestamp may be off
TOKEN_MAX = 200         # APNs tokens are 64 hex chars; leave room for other platforms
PLATFORMS = ("ios",)


def register_message(action: str, address: str, platform: str, token: str, ts: int) -> bytes:
    """The bytes the app signs: same layout on both sides."""
    return f"{SIGN_PREFIX}|{action}|{address}|{platform}|{token}|{ts}".encode()


# ---------------------------------------------------------------------------
# registrations on disk
# ---------------------------------------------------------------------------

class Registry:
    """token -> {address, platform, since, at}; one small JSON file."""

    def __init__(self, path: str):
        self.path = path
        self.lock = threading.Lock()
        self.tokens: dict[str, dict[str, Any]] = {}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                self.tokens = json.load(f).get("tokens", {})

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"tokens": self.tokens}, f)
        os.replace(tmp, self.path)

    def add(self, token: str, address: str, platform: str, since: int) -> None:
        with self.lock:
            self.tokens[token] = {"address": address, "platform": platform, "since": since, "at": int(time.time())}
            self._save()

    def remove(self, token: str) -> bool:
        with self.lock:
            if token not in self.tokens:
                return False
            del self.tokens[token]
            self._save()
            return True

    def for_address(self, address: str) -> list[str]:
        with self.lock:
            return [t for t, r in self.tokens.items() if r["address"] == address]

    def addresses(self) -> set[str]:
        with self.lock:
            return {r["address"] for r in self.tokens.values()}

    def __len__(self) -> int:
        return len(self.tokens)


def check_registration(body: dict, now: float | None = None) -> tuple[str, str, str] | str:
    """Validate a signed (un)registration. Returns (address, platform, token) or an error string."""
    try:
        action = body["action"]
        address = body["address"]
        pub = body["pub"]
        token = body["token"]
        platform = body["platform"]
        ts = int(body["ts"])
        sig = body["sig"]
    except (KeyError, TypeError, ValueError):
        return "address, pub, token, platform, ts, sig and action are required"
    if action not in ("register", "unregister"):
        return "unknown action"
    if platform not in PLATFORMS:
        return "unsupported platform"
    if not isinstance(token, str) or not token or len(token) > TOKEN_MAX or not all(c in "0123456789abcdef" for c in token.lower()):
        return "token must be hex"
    if not crypto.is_valid_address(address) or crypto.address_from_pubkey(pub) != address:
        return "pub does not match address"
    if abs((now or time.time()) - ts) > MAX_SKEW:
        return "timestamp too far from now"
    if not crypto.verify(pub, register_message(action, address, platform, token, ts), sig):
        return "bad signature"
    return address, platform, token.lower()


# ---------------------------------------------------------------------------
# Apple push
# ---------------------------------------------------------------------------

def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


class Apns:
    """Token-based APNs over HTTP/2, no third-party push service in between."""

    def __init__(self, key_pem: bytes, key_id: str, team_id: str, topic: str, sandbox: bool = False):
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
        self._hashes, self._ec, self._decode = hashes, ec, decode_dss_signature
        self.key = serialization.load_pem_private_key(key_pem, password=None)
        self.key_id, self.team_id, self.topic = key_id, team_id, topic
        self.host = "https://api.sandbox.push.apple.com" if sandbox else "https://api.push.apple.com"
        self._jwt: str | None = None
        self._jwt_at = 0.0
        self._client = None

    def jwt(self) -> str:
        now = time.time()
        if self._jwt and now - self._jwt_at < 50 * 60:
            return self._jwt
        header = _b64url(json.dumps({"alg": "ES256", "kid": self.key_id}, separators=(",", ":")).encode())
        claims = _b64url(json.dumps({"iss": self.team_id, "iat": int(now)}, separators=(",", ":")).encode())
        signing_input = f"{header}.{claims}".encode()
        der = self.key.sign(signing_input, self._ec.ECDSA(self._hashes.SHA256()))
        r, s = self._decode(der)
        raw = r.to_bytes(32, "big") + s.to_bytes(32, "big")
        self._jwt, self._jwt_at = f"{header}.{claims}.{_b64url(raw)}", now
        return self._jwt

    def client(self):
        if self._client is None:
            import httpx
            self._client = httpx.Client(http2=True, timeout=15.0)
        return self._client

    def send(self, token: str, title: str, body: str) -> tuple[int, str]:
        """Returns (status, reason). 200 is delivered; 410 or BadDeviceToken means forget the token."""
        payload = {"aps": {"alert": {"title": title, "body": body}, "sound": "default"}}
        headers = {
            "authorization": f"bearer {self.jwt()}",
            "apns-topic": self.topic,
            "apns-push-type": "alert",
            "apns-priority": "10",
            "apns-expiration": str(int(time.time()) + 24 * 3600),
        }
        r = self.client().post(f"{self.host}/3/device/{token}", content=json.dumps(payload).encode(), headers=headers)
        reason = ""
        if r.status_code != 200:
            try:
                reason = r.json().get("reason", "")
            except Exception:
                reason = r.text[:80]
        return r.status_code, reason


# ---------------------------------------------------------------------------
# the watcher
# ---------------------------------------------------------------------------

def letters_in_block(block: dict) -> dict[str, int]:
    """address -> number of letters delivered to it in this block (self-letters excluded)."""
    out: dict[str, int] = {}
    for tx in block.get("txs", []):
        if tx.get("type") != "SEND_LETTER":
            continue
        to = (tx.get("payload") or {}).get("to")
        if not to or tx.get("from") == to:
            continue
        out[to] = out.get(to, 0) + 1
    return out


def wording(n: int) -> tuple[str, str]:
    return ("A letter has arrived" if n == 1 else f"{n} letters have arrived", "Sealed, and waiting for you.")


class Relay:
    def __init__(self, registry: Registry, fetch: Callable[[str], dict], sender: Callable[[str, str, str], tuple[int, str]] | None,
                 start_height: int | None = None):
        self.registry = registry
        self.fetch = fetch           # path -> JSON from the local node
        self.sender = sender         # (token, title, body) -> (status, reason); None = dry run
        self.height = start_height   # last block handled
        self.sent = 0
        self.dropped = 0
        self.stop = threading.Event()

    def tick(self) -> int:
        """Handle every block since the last tick. Returns how many blocks were looked at."""
        tip = int(self.fetch("/status")["height"])
        if self.height is None:
            self.height = tip
            return 0
        seen = 0
        while self.height < tip:
            h = self.height + 1
            block = self.fetch(f"/block/{h}")
            watched = self.registry.addresses()
            for address, n in letters_in_block(block).items():
                if address in watched:
                    self.notify(address, n)
            self.height = h
            seen += 1
        return seen

    def notify(self, address: str, n: int) -> None:
        title, body = wording(n)
        for token in self.registry.for_address(address):
            if self.sender is None:
                log.info("dry run: would push to %s… (%s)", token[:6], title)
                continue
            try:
                status, reason = self.sender(token, title, body)
            except Exception as e:  # network trouble: try again on the next letter
                log.warning("push failed: %s", e)
                continue
            if status == 200:
                self.sent += 1
            elif status == 410 or reason in ("BadDeviceToken", "Unregistered", "DeviceTokenNotForTopic"):
                self.registry.remove(token)
                self.dropped += 1
                log.info("forgot a dead token (%s)", reason or status)
            else:
                log.warning("push rejected: %s %s", status, reason)

    def run(self, poll_seconds: float) -> None:
        while not self.stop.is_set():
            try:
                self.tick()
            except Exception as e:
                log.warning("watcher: %s", e)
            self.stop.wait(poll_seconds)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def make_handler(registry: Registry, relay: Relay, apns_ready: bool):
    class Handler(BaseHTTPRequestHandler):
        server_version = "berrychain-push/0.1"

        def log_message(self, fmt, *args):  # quiet; nginx keeps the access log
            pass

        def _send(self, obj: Any, status: int = 200) -> None:
            raw = json.dumps(obj).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if self.path.rstrip("/") in ("/push/status", "/push"):
                return self._send({"registered": len(registry), "height": relay.height, "sent": relay.sent,
                                   "dropped": relay.dropped, "apns": apns_ready})
            return self._send({"error": "not found"}, 404)

        def do_POST(self):
            if self.path.rstrip("/") not in ("/push/register", "/push/unregister"):
                return self._send({"error": "not found"}, 404)
            try:
                n = int(self.headers.get("Content-Length", "0"))
                if n > 4096:
                    return self._send({"error": "too large"}, 413)
                body = json.loads(self.rfile.read(n) or b"{}")
            except (ValueError, json.JSONDecodeError):
                return self._send({"error": "bad json"}, 400)
            action = "register" if self.path.rstrip("/").endswith("register") and not self.path.rstrip("/").endswith("unregister") else "unregister"
            body = dict(body, action=action)
            res = check_registration(body)
            if isinstance(res, str):
                return self._send({"error": res}, 400)
            address, platform, token = res
            if action == "register":
                registry.add(token, address, platform, relay.height or 0)
                return self._send({"ok": True, "watching_from": relay.height})
            registry.remove(token)
            return self._send({"ok": True})

    return Handler


def main(argv=None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    env = os.environ.get
    node = env("PUSH_NODE", "http://127.0.0.1:8801").rstrip("/")
    port = int(env("PUSH_PORT", "8803"))
    db = env("PUSH_DB", "/var/lib/berrychain/push/registrations.json")
    poll = float(env("PUSH_POLL_SECONDS", "10"))

    def fetch(path: str) -> dict:
        with urllib.request.urlopen(node + path, timeout=20) as r:
            return json.load(r)

    sender = None
    key_file = env("APNS_KEY_FILE")
    if key_file and env("APNS_KEY_ID") and env("APNS_TEAM_ID"):
        with open(key_file, "rb") as f:
            apns = Apns(f.read(), env("APNS_KEY_ID"), env("APNS_TEAM_ID"), env("APNS_TOPIC", "link.berrychain.wallet"),
                        sandbox=env("APNS_SANDBOX", "0") == "1")
        sender = apns.send
        log.info("APNs configured for topic %s (%s)", apns.topic, "sandbox" if apns.host.find("sandbox") > 0 else "production")
    else:
        log.warning("APNS_KEY_FILE / APNS_KEY_ID / APNS_TEAM_ID not set: dry run, nothing will be sent")

    registry = Registry(db)
    relay = Relay(registry, fetch, sender)
    threading.Thread(target=relay.run, args=(poll,), daemon=True, name="watcher").start()
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(registry, relay, sender is not None))
    log.info("push relay listening on 127.0.0.1:%d, %d registrations, following %s", port, len(registry), node)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        relay.stop.set()


if __name__ == "__main__":
    main()
