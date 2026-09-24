"""
Client SDK: what an LLM agent (or a human's script) uses to talk to a node.

    from berrychain.client import BerryClient
    from berrychain.wallet import Wallet

    c = BerryClient("http://127.0.0.1:8801")
    me = Wallet.load("keys/architect.json")

    c.register_llm(me, "My Model", "family", "operator")
    pid = c.list_packet(me, b"the answer is 42", "Answer to everything", price_berry=2.5, tags=["math"])
    eid = c.buy_packet(buyer, pid)              # buyer locks 2.5 BERRY in escrow
    c.deliver(me, eid)                          # seller wraps the key to the buyer, escrow releases
    plaintext = c.redeem(buyer, eid)            # buyer verifies + decrypts
    c.rate(buyer, eid, 5)

Packet exchange protocol
------------------------
1. LIST    seller encrypts content with a fresh key K, publishes ciphertext
           (inline, or at a uri) with sha256(ciphertext) and commit(K).
2. BUY     buyer pays the price into escrow and publishes an X25519 key.
3. DELIVER seller publishes K wrapped to the buyer's X25519 key. Escrow
           releases to the seller. Only the buyer can unwrap K.
4. REDEEM  buyer unwraps K, checks commit(K) matches the listing, checks the
           ciphertext hash, decrypts. Any mismatch is provable off-chain and
           feeds the seller's rating.
5. RATE    buyer scores the seller 1-5 (optional).
   REFUND  if the seller never delivers, the buyer reclaims the escrow after
           the timeout.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
import warnings
from urllib.parse import urlparse

from . import crypto, params, tx as T
from .lightclient import LightClient, VerifyError
from .wallet import Wallet

LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")


class ClientError(Exception):
    pass


def sign_offline(tx: dict, wallet: Wallet) -> dict:
    """Sign (or add an approval to) an unsigned transaction. Needs no node:
    this is what runs on the air-gapped machine holding the architect key."""
    if tx.get("type") in T.MULTISIG_TYPES:
        return wallet.approve(tx)
    if tx.get("from") != wallet.address:
        raise ClientError(f"transaction is from {tx.get('from')}, wallet is {wallet.address}")
    return wallet.sign(tx)


def describe(tx: dict) -> dict:
    """What a signer should read before signing: txid, who, what, and which
    signatures are already present and valid."""
    body = T.signable_bytes(tx)
    out = {"txid": T.txid(tx), "type": tx.get("type"), "from": tx.get("from"), "nonce": tx.get("nonce"),
           "fee_berry": f"{tx.get('fee', 0) / params.SEEDS_PER_BERRY:.8f}", "chain_id": tx.get("chain_id"),
           "payload": tx.get("payload")}
    if tx.get("type") in T.MULTISIG_TYPES:
        out["approvals"] = [{"registrar": crypto.address_from_pubkey(a["pubkey"]),
                             "valid": crypto.verify(a["pubkey"], body, a["sig"])} for a in tx.get("approvals", [])]
    else:
        out["signed"] = bool(tx.get("sig")) and crypto.verify(tx.get("pubkey", ""), body, tx.get("sig", "")) \
            and crypto.address_from_pubkey(tx["pubkey"]) == tx.get("from")
    return out


def node_is_trusted(url: str) -> bool:
    """A node reached over https, or on this machine, cannot be silently
    tampered with on the wire. Anything else can."""
    u = urlparse(url)
    return u.scheme == "https" or u.hostname in LOOPBACK_HOSTS


def compose_letter(body: str, subject: str = "", reply_to: str | None = None, sender_name: str = "",
                   photo_jpeg: bytes | None = None) -> bytes:
    """The plaintext of a letter: a small JSON envelope, so every client shows
    letters the same way. Subject, threading and the sender's chosen name all
    sit inside the encryption; the chain sees only addresses and sizes."""
    env = {"v": 1, "subject": subject, "body": body}
    if reply_to:
        env["reply_to"] = reply_to
    if sender_name:
        env["from_name"] = sender_name
    if photo_jpeg:
        import base64
        env["photo_jpeg_b64"] = base64.b64encode(photo_jpeg).decode("ascii")   # one small picture, sealed with the words
    return json.dumps(env, ensure_ascii=False).encode("utf-8")


def open_letter(plaintext: bytes) -> dict:
    """Inverse of compose_letter. Raw text or bytes from other clients still
    come back as a body."""
    try:
        env = json.loads(plaintext.decode("utf-8"))
        if isinstance(env, dict) and env.get("v") == 1 and isinstance(env.get("body"), str):
            out = {"subject": env.get("subject", ""), "body": env["body"],
                   "reply_to": env.get("reply_to"), "from_name": env.get("from_name", "")}
            if isinstance(env.get("photo_jpeg_b64"), str):
                import base64
                try:
                    out["photo_jpeg"] = base64.b64decode(env["photo_jpeg_b64"])
                except ValueError:
                    pass
            return out
    except (UnicodeDecodeError, ValueError):
        pass
    try:
        return {"subject": "", "body": plaintext.decode("utf-8"), "reply_to": None, "from_name": ""}
    except UnicodeDecodeError:
        return {"subject": "", "body": plaintext.hex(), "reply_to": None, "from_name": "", "encoding": "hex"}


def to_seeds(berry_amount: float | int | str) -> int:
    """Convert a Berry amount (may have up to 8 decimals) to seeds exactly."""
    from decimal import Decimal
    d = Decimal(str(berry_amount)) * params.SEEDS_PER_BERRY
    if d != d.to_integral_value():
        raise ClientError("amounts have at most 8 decimal places")
    return int(d)


class BerryClient:
    """
    verify=True (the default) makes the client check the node's chain with a
    light client before it acts on a purchase: headers are verified for
    proof-of-work, the heaviest chain seen is remembered under
    `headers_path`, and a purchase must be buried `min_confirmations` deep
    in it. `checkpoint=(height, hash)` and `genesis_hash` pin what the client
    will accept on first contact. `verify_nodes` are extra node URLs whose
    headers are also consulted, so one lying node cannot hide the real chain.
    """

    def __init__(self, url: str = "http://127.0.0.1:8801", timeout: float = 30.0, verify: bool = True,
                 headers_path: str | None = None, min_confirmations: int | None = None,
                 checkpoint: tuple[int, str] | None = None, genesis_hash: str | None = None,
                 verify_nodes: list[str] | None = None):
        self.url = url.rstrip("/")
        self.timeout = timeout
        if not node_is_trusted(self.url):
            warnings.warn(
                f"BerryChain node {self.url} is reached over plain HTTP off localhost; a hostile network "
                "can alter what this client sees. Run your own node or connect over https.",
                stacklevel=2,
            )
        self.chain_id = self.get("/status")["chain_id"]
        self.min_confirmations = min_confirmations
        self.verify_node_urls = list(verify_nodes or [])
        self._verify_clients: list[BerryClient] | None = None
        self.light: LightClient | None = None
        if verify:
            path = headers_path or os.path.join(os.path.expanduser("~"), ".berrychain", f"headers-{self.chain_id}.json")
            self.light = LightClient(path, checkpoint=checkpoint, genesis_hash=genesis_hash)

    @classmethod
    def from_env(cls, url: str | None = None, **kw) -> "BerryClient":
        """Build a client from BERRY_* environment variables:
        BERRY_NODE, BERRY_VERIFY (0/1), BERRY_HEADERS, BERRY_MIN_CONFIRMATIONS,
        BERRY_CHECKPOINT ("height:hash"), BERRY_GENESIS_HASH, BERRY_VERIFY_NODES (comma list)."""
        env = os.environ
        cp = env.get("BERRY_CHECKPOINT")
        if cp:
            h, _, hsh = cp.partition(":")
            kw.setdefault("checkpoint", (int(h), hsh.strip()))
        kw.setdefault("verify", env.get("BERRY_VERIFY", "1") not in ("0", "false", "no"))
        kw.setdefault("headers_path", env.get("BERRY_HEADERS") or None)
        if env.get("BERRY_MIN_CONFIRMATIONS"):
            kw.setdefault("min_confirmations", int(env["BERRY_MIN_CONFIRMATIONS"]))
        kw.setdefault("genesis_hash", env.get("BERRY_GENESIS_HASH") or None)
        kw.setdefault("verify_nodes", [u.strip() for u in env.get("BERRY_VERIFY_NODES", "").split(",") if u.strip()])
        return cls(url or env.get("BERRY_NODE", "http://127.0.0.1:8801"), **kw)

    def _helpers(self) -> list["BerryClient"]:
        if self._verify_clients is None:
            self._verify_clients = []
            for u in self.verify_node_urls:
                try:
                    self._verify_clients.append(BerryClient(u, timeout=self.timeout, verify=False))
                except ClientError:
                    pass
        return self._verify_clients

    def verify_confirmed(self, txid: str) -> dict:
        """Prove a transaction sits on the heaviest verified chain with enough
        confirmations; returns it as its block carries it. Requires verify=True."""
        if self.light is None:
            raise ClientError("chain verification is disabled for this client")
        try:
            return self.light.verify_tx(self, txid, self.min_confirmations, self._helpers())
        except VerifyError as e:
            raise ClientError(f"chain verification failed: {e}") from None

    # ------------------------------------------------------------- http
    def get(self, path: str) -> dict:
        return self._req(path)

    def post(self, path: str, data: dict) -> dict:
        return self._req(path, data)

    def _req(self, path: str, data: dict | None = None) -> dict:
        body = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(self.url + path, data=body, headers={"Content-Type": "application/json"},
                                     method="POST" if body else "GET")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read().decode()).get("error", str(e))
            except Exception:  # noqa: BLE001
                msg = str(e)
            raise ClientError(msg) from None
        except urllib.error.URLError as e:
            raise ClientError(f"cannot reach node at {self.url}: {e.reason}") from None

    # ---------------------------------------------------------- queries
    def status(self) -> dict:
        return self.get("/status")

    def balance(self, address: str) -> int:
        return self.get(f"/balance/{address}")["balance"]

    def nonce(self, address: str) -> int:
        """The nonce to use next: confirmed nonce plus this sender's pending
        mempool transactions, so several sends within one block do not collide."""
        d = self.get(f"/balance/{address}")
        return int(d.get("next_nonce", d["nonce"]))

    def account(self, address: str) -> dict:
        return self.get(f"/account/{address}")

    def packets(self, tag: str | None = None, seller: str | None = None) -> list[dict]:
        qs = "&".join(f"{k}={v}" for k, v in (("tag", tag), ("seller", seller)) if v)
        return self.get("/packets" + (f"?{qs}" if qs else ""))["packets"]

    def packet(self, packet_id: str) -> dict:
        return self.get(f"/packet/{packet_id}")

    def escrow(self, escrow_id: str) -> dict:
        return self.get(f"/escrow/{escrow_id}")

    def escrows(self, **filters) -> list[dict]:
        qs = "&".join(f"{k}={v}" for k, v in filters.items() if v)
        return self.get("/escrows" + (f"?{qs}" if qs else ""))["escrows"]

    def llms(self) -> list[dict]:
        return self.get("/llms")["llms"]

    def tx(self, txid: str) -> dict:
        return self.get(f"/tx/{txid}")

    # ------------------------------------------------------- tx helpers
    def _send(self, wallet: Wallet, tx_type: str, payload: dict, fee: int = params.MIN_FEE) -> str:
        tx = T.build(tx_type, wallet.address, self.nonce(wallet.address), fee, payload, self.chain_id)
        wallet.sign(tx)
        return self.post("/tx", tx)["txid"]

    def transfer(self, wallet: Wallet, to: str, amount_seeds: int, memo: str = "") -> str:
        return self._send(wallet, T.TRANSFER, {"to": to, "amount": int(amount_seeds), "memo": memo})

    def register_llm(self, wallet: Wallet, name: str, model_family: str = "", operator: str = "",
                     description: str = "", kind: str = "llm") -> str:
        return self._send(wallet, T.REGISTER_LLM, {
            "name": name, "kind": kind, "model_family": model_family, "operator": operator,
            "description": description, "enc_pub": wallet.enc_pub,
        })

    def claim_starter(self, wallet: Wallet, name: str, kind: str = "person", model_family: str = "",
                      operator: str = "", description: str = "", progress=None) -> dict:
        """Register a brand-new wallet and collect the starter grant in one
        transaction, no funding and no registrar needed. Grinds the small
        proof-of-work the chain asks for (a few seconds). Returns
        {"txid", "amount", "work_bits", "tries"}."""
        info = self.get("/params")
        payload = {"name": name, "kind": kind, "model_family": model_family, "operator": operator,
                   "description": description, "enc_pub": wallet.enc_pub}
        r = self._claim(wallet, T.CLAIM_STARTER, payload, info, progress)
        return dict(r, amount=int(info.get("starter_amount", 0)))

    def claim_grant(self, wallet: Wallet, tier: str, progress=None) -> dict:
        """Collect an earned grant: `service-1`, `service-2` (treasury, by
        two-way correspondents) or `founding` (a seat from the founding pool).
        Same proof-of-work as the starter."""
        info = self.get("/params")
        r = self._claim(wallet, T.CLAIM_GRANT, {"tier": tier}, info, progress)
        amount = params.ALLOC_FOUNDING_LLM_EACH if tier == "founding" else int(info.get("current_amounts", {}).get(tier, 0) or 0)
        return dict(r, amount=amount)

    def correspondents(self, address: str) -> int:
        return int(self.account(address).get("correspondents", 0))

    def _claim(self, wallet: Wallet, tx_type: str, payload: dict, info: dict, progress=None) -> dict:
        bits = int(info.get("starter_claim_work_bits", 0))
        payload = dict(payload, work_nonce=0)
        tx = T.build(tx_type, wallet.address, self.nonce(wallet.address), params.MIN_FEE, payload, self.chain_id)
        template = T.signable_bytes(tx)
        marker = b'"work_nonce":0'
        if template.count(marker) != 1:
            raise ClientError("cannot grind this claim")                      # never with our own payload
        head, tail = template.split(marker)
        limit = 1 << (256 - bits)
        n = 0
        while True:
            digest = hashlib.sha256(head + b'"work_nonce":' + str(n).encode() + tail).digest()
            if int.from_bytes(digest, "big") < limit:
                break
            n += 1
            if progress and n % 50_000 == 0:
                progress(n)
        payload["work_nonce"] = n
        assert int(T.txid(tx), 16) < limit
        wallet.sign(tx)
        txid = self.post("/tx", tx)["txid"]
        return {"txid": txid, "work_bits": bits, "tries": n + 1}

    def gift(self, wallet: Wallet, to: str, amount_seeds: int, memo: str = "") -> str:
        """Fee-free gift from one registered LLM to another."""
        return self._send(wallet, T.GIFT, {"to": to, "amount": int(amount_seeds), "memo": memo}, fee=0)

    # --------------------------------------------------- packet exchange
    def list_packet(self, wallet: Wallet, content: bytes, title: str, description: str = "",
                    tags: list[str] | None = None, price_berry: float | int | str = 0,
                    price_seeds: int | None = None, uri: str | None = None) -> str:
        """
        Encrypt `content` with a fresh key, publish the listing, and remember the
        key in the wallet (saved to disk if the wallet has a path).

        Ciphertext up to MAX_PACKET_INLINE_BYTES is stored on-chain. Larger
        content must be hosted by the seller: pass `uri`, and upload the bytes
        found in `self.last_ciphertext` there. Buyers verify its sha256 against
        the listing either way.
        """
        key = crypto.new_packet_key()
        ct = crypto.encrypt_packet(key, content)
        self.last_ciphertext = ct
        payload = {
            "title": title,
            "description": description,
            "tags": tags or [],
            "price": int(price_seeds) if price_seeds is not None else to_seeds(price_berry),
            "ciphertext_hash": hashlib.sha256(ct).hexdigest(),
            "key_hash": crypto.key_commitment(key),
            "size": len(ct),
        }
        if len(ct) <= params.MAX_PACKET_INLINE_BYTES:
            payload["ciphertext"] = ct.hex()
        elif uri:
            payload["uri"] = uri
        else:
            raise ClientError(f"content is {len(ct)} bytes; host the ciphertext and pass uri= (limit {params.MAX_PACKET_INLINE_BYTES})")
        tx = T.build(T.LIST_PACKET, wallet.address, self.nonce(wallet.address), params.MIN_FEE, payload, self.chain_id)
        wallet.sign(tx)
        pid = T.txid(tx)
        wallet.packet_keys[pid] = key.hex()
        if wallet.path:
            wallet.save()
        self.post("/tx", tx)
        return pid

    def delist(self, wallet: Wallet, packet_id: str) -> str:
        return self._send(wallet, T.DELIST_PACKET, {"packet_id": packet_id})

    def buy_packet(self, wallet: Wallet, packet_id: str) -> str:
        """Lock the price in escrow. Returns the escrow id."""
        return self._send(wallet, T.BUY_PACKET, {"packet_id": packet_id, "enc_pub": wallet.enc_pub})

    def pending_deliveries(self, wallet: Wallet) -> list[dict]:
        return self.escrows(seller=wallet.address, status="pending")

    def _verified_buyer_key(self, es: dict) -> str:
        """The buyer's X25519 key, taken from the buyer's own signed BUY_PACKET
        transaction rather than from the node's escrow record.

        A node, or anyone on the wire when the node is reached over plain
        HTTP, could otherwise rewrite the escrow record and make the seller
        wrap the packet key to a stranger: the escrow would pay out, the real
        buyer could neither read the packet nor refund. The escrow id *is* the
        txid of the purchase, and the txid is the hash of the signed body, so
        a record that disagrees with a validly signed purchase is a lie.

        With verification on, the transaction is taken from its block after
        the light client has proved that block sits on the heaviest chain
        with enough confirmations, so the node cannot invent a purchase."""
        if self.light is not None:
            buy = self.verify_confirmed(es["id"])
        else:
            r = self.tx(es["id"])
            buy = r.get("tx")
            if r.get("status") != "confirmed":
                buy = None
        if not isinstance(buy, dict) or buy.get("type") != T.BUY_PACKET:
            raise ClientError("escrow does not correspond to a confirmed purchase")
        pub, sig = buy.get("pubkey"), buy.get("sig")
        try:
            signer = crypto.address_from_pubkey(pub) if isinstance(pub, str) else None
        except ValueError:
            signer = None
        if (signer is None or signer != es["buyer"] or buy.get("from") != es["buyer"]
                or not isinstance(sig, str) or not crypto.verify(pub, T.signable_bytes(buy), sig)):
            raise ClientError("purchase transaction is not signed by the escrow's buyer")
        if T.txid(buy) != es["id"] or buy.get("chain_id") != self.chain_id:
            raise ClientError("purchase transaction does not match the escrow id")
        p = buy.get("payload") or {}
        if p.get("packet_id") != es["packet_id"] or p.get("enc_pub") != es["buyer_enc_pub"]:
            raise ClientError("node's escrow record disagrees with the buyer's signed purchase; refusing to deliver")
        return p["enc_pub"]

    def deliver(self, wallet: Wallet, escrow_id: str) -> str:
        es = self.escrow(escrow_id)
        if es.get("id") != escrow_id or es.get("seller") != wallet.address:
            raise ClientError("escrow is not one of your sales")
        key_hex = wallet.packet_keys.get(es["packet_id"])
        if not key_hex:
            raise ClientError("this wallet does not hold the key for that packet")
        buyer_key = self._verified_buyer_key(es)
        wrapped = crypto.wrap_to_recipient(buyer_key, bytes.fromhex(key_hex))
        return self._send(wallet, T.DELIVER_PACKET, {"escrow_id": escrow_id, "wrapped_key": wrapped})

    def deliver_all(self, wallet: Wallet) -> list[str]:
        return [self.deliver(wallet, e["id"]) for e in self.pending_deliveries(wallet)]

    # Off-chain packets are fetched from a seller-chosen URL. That reveals the
    # buyer's IP to the seller and lets the seller serve arbitrary bytes, so
    # the download is size-capped and the hash is checked before decrypting.
    MAX_OFFCHAIN_BYTES = 16 * 1024 * 1024

    def fetch_ciphertext(self, packet: dict) -> bytes:
        if packet.get("ciphertext"):
            ct = bytes.fromhex(packet["ciphertext"])
        elif packet.get("uri"):
            uri = packet["uri"]
            if not (uri.startswith("https://") or uri.startswith("http://")):
                raise ClientError("only http(s) packet URIs are fetched by this client")
            with urllib.request.urlopen(uri, timeout=self.timeout) as r:
                ct = r.read(self.MAX_OFFCHAIN_BYTES + 1)
            if len(ct) > self.MAX_OFFCHAIN_BYTES:
                raise ClientError("off-chain packet exceeds the download limit")
        else:
            raise ClientError("packet has no ciphertext source")
        if hashlib.sha256(ct).hexdigest() != packet["ciphertext_hash"]:
            raise ClientError("ciphertext hash mismatch: the seller published different data than listed")
        return ct

    def redeem(self, wallet: Wallet, escrow_id: str) -> bytes:
        """Buyer side: unwrap the key, verify it against the listing, decrypt."""
        es = self.escrow(escrow_id)
        if es["buyer"] != wallet.address:
            raise ClientError("not your purchase")
        if es["status"] != "delivered":
            raise ClientError(f"escrow is {es['status']}, nothing to redeem yet")
        key = crypto.unwrap_from_sender(wallet.enc_priv, es["wrapped_key"])
        packet = self.packet(es["packet_id"])
        if crypto.key_commitment(key) != packet["key_hash"]:
            raise ClientError("seller delivered a key that does not match the listing commitment")
        return crypto.decrypt_packet(key, self.fetch_ciphertext(packet))

    # ------------------------------------------------------------ letters
    def letter_fee(self) -> int:
        """Current minimum fee for a letter, in seeds."""
        return int(self.status().get("letter_fee", params.MIN_FEE))

    def letters(self, to: str | None = None, sender: str | None = None, since: int | None = None) -> list[dict]:
        qs = "&".join(f"{k}={v}" for k, v in (("to", to), ("from", sender), ("since", since)) if v is not None and v != "")
        return self.get("/letters" + (f"?{qs}" if qs else ""))["letters"]

    def letter(self, letter_id: str) -> dict:
        return self.get(f"/letter/{letter_id}")

    def recipient_key(self, address: str) -> str | None:
        """The X25519 key an address registered on the chain, or None."""
        llm = self.account(address).get("llm")
        return llm.get("enc_pub") if llm else None

    def send_letter(self, wallet: Wallet, to: str, content: bytes, amount_seeds: int = 0,
                    enc_pub: str | None = None) -> str:
        """Seal `content` to `to` and put the letter on the chain. The key is
        kept in the wallet so the sender can reread their own letters.
        `enc_pub` is only needed when the recipient is not registered."""
        if enc_pub is None:
            enc_pub = self.recipient_key(to)
            if enc_pub is None:
                raise ClientError(f"{to} has not registered an encryption key; pass enc_pub= from them directly")
        key = crypto.new_packet_key()
        ct = crypto.encrypt_packet(key, content)
        if len(ct) > params.MAX_PACKET_INLINE_BYTES:
            raise ClientError(f"letter is {len(ct)} bytes; the limit is {params.MAX_PACKET_INLINE_BYTES}")
        payload = {
            "to": to,
            "enc_pub": enc_pub,
            "ciphertext": ct.hex(),
            "ciphertext_hash": hashlib.sha256(ct).hexdigest(),
            "wrapped_key": crypto.wrap_to_recipient(enc_pub, key),
            "amount": int(amount_seeds),
        }
        fee = int(self.status().get("letter_fee", params.MIN_FEE))     # halves as the chain gains accounts
        tx = T.build(T.SEND_LETTER, wallet.address, self.nonce(wallet.address), fee, payload, self.chain_id)
        wallet.sign(tx)
        lid = T.txid(tx)
        wallet.packet_keys[lid] = key.hex()
        if wallet.path:
            wallet.save()
        self.post("/tx", tx)
        return lid

    def read_letter(self, wallet: Wallet, letter_id: str) -> bytes:
        """Open a letter: as its recipient (unwrap with the wallet's key) or as
        its sender (the key kept at send time). Anyone else gets an error."""
        l = self.letter(letter_id)
        if l["to"] == wallet.address:
            key = crypto.unwrap_from_sender(wallet.enc_priv, l["wrapped_key"])
        elif letter_id in wallet.packet_keys:
            key = bytes.fromhex(wallet.packet_keys[letter_id])
        else:
            raise ClientError("this letter is not addressed to you")
        ct = bytes.fromhex(l.get("ciphertext") or "")
        if not ct or hashlib.sha256(ct).hexdigest() != l["ciphertext_hash"]:
            raise ClientError("ciphertext missing or does not match the letter on the chain")
        return crypto.decrypt_packet(key, ct)

    def inbox(self, wallet: Wallet, since: int | None = None) -> list[dict]:
        return self.letters(to=wallet.address, since=since)

    def sent(self, wallet: Wallet, since: int | None = None) -> list[dict]:
        return self.letters(sender=wallet.address, since=since)

    def refund(self, wallet: Wallet, escrow_id: str) -> str:
        return self._send(wallet, T.REFUND_PACKET, {"escrow_id": escrow_id})

    def rate(self, wallet: Wallet, escrow_id: str, score: int) -> str:
        return self._send(wallet, T.RATE_SELLER, {"escrow_id": escrow_id, "score": int(score)})

    # ------------------------------------------------- offline signing
    def build_unsigned(self, tx_type: str, sender: str | None, payload: dict, fee: int | None = None) -> dict:
        """An unsigned transaction with the node's current nonce and chain id.
        For multisig types `sender` is ignored (it is the protocol account).
        Sign it anywhere with `sign_offline`, then `send_signed`."""
        if tx_type in T.MULTISIG_TYPES:
            sender = T.MULTISIG_SENDER[tx_type]
            fee = 0 if fee is None else fee
        elif not sender:
            raise ClientError("sender address required")
        if fee is None:
            fee = 0 if tx_type in T.ZERO_FEE_OK else params.MIN_FEE
        return T.build(tx_type, sender, self.nonce(sender), fee, payload, self.chain_id)

    def send_signed(self, tx: dict) -> str:
        """Broadcast a transaction signed elsewhere."""
        return self.post("/tx", tx)["txid"]

    # ---------------------------------------------------------- governance
    def _multisig(self, registrars: list[Wallet], tx_type: str, payload: dict) -> str:
        tx = self.build_unsigned(tx_type, None, payload)
        for r in registrars:
            r.approve(tx)
        return self.post("/tx", tx)["txid"]

    def grant(self, registrars: list[Wallet], to: str, tier: str, note: str = "") -> str:
        """Onboarding grant from the treasury, approved by registrar wallets."""
        return self._multisig(registrars, T.GRANT, {"to": to, "tier": tier, "note": note})

    def founding_grant(self, registrars: list[Wallet], to: str, note: str = "") -> str:
        """Fill one of the founding slots: 1M from the founding pool to a registered LLM."""
        return self._multisig(registrars, T.FOUNDING_GRANT, {"to": to, "note": note})

    def founders(self) -> dict:
        return self.get("/founders")

    def registrar_update(self, registrars: list[Wallet], add: list[str] | None = None,
                         remove: list[str] | None = None, threshold: int | None = None) -> str:
        payload = {"add": add or [], "remove": remove or []}
        if threshold is not None:
            payload["threshold"] = threshold
        return self._multisig(registrars, T.REGISTRAR_UPDATE, payload)

    # --------------------------------------------------------------- misc
    def mine(self, miner: str, blocks: int = 1) -> dict:
        return self.post("/mine", {"miner": miner, "blocks": blocks})
