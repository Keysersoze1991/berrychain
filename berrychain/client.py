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
import urllib.error
import urllib.request

from . import crypto, params, tx as T
from .wallet import Wallet


class ClientError(Exception):
    pass


def to_seeds(berry_amount: float | int | str) -> int:
    """Convert a Berry amount (may have up to 8 decimals) to seeds exactly."""
    from decimal import Decimal
    d = Decimal(str(berry_amount)) * params.SEEDS_PER_BERRY
    if d != d.to_integral_value():
        raise ClientError("amounts have at most 8 decimal places")
    return int(d)


class BerryClient:
    def __init__(self, url: str = "http://127.0.0.1:8801", timeout: float = 30.0):
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.chain_id = self.get("/status")["chain_id"]

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
        return self.get(f"/balance/{address}")["nonce"]

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

    def register_llm(self, wallet: Wallet, name: str, model_family: str = "", operator: str = "", description: str = "") -> str:
        return self._send(wallet, T.REGISTER_LLM, {
            "name": name, "model_family": model_family, "operator": operator,
            "description": description, "enc_pub": wallet.enc_pub,
        })

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

    def deliver(self, wallet: Wallet, escrow_id: str) -> str:
        es = self.escrow(escrow_id)
        key_hex = wallet.packet_keys.get(es["packet_id"])
        if not key_hex:
            raise ClientError("this wallet does not hold the key for that packet")
        wrapped = crypto.wrap_to_recipient(es["buyer_enc_pub"], bytes.fromhex(key_hex))
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

    def refund(self, wallet: Wallet, escrow_id: str) -> str:
        return self._send(wallet, T.REFUND_PACKET, {"escrow_id": escrow_id})

    def rate(self, wallet: Wallet, escrow_id: str, score: int) -> str:
        return self._send(wallet, T.RATE_SELLER, {"escrow_id": escrow_id, "score": int(score)})

    # ---------------------------------------------------------- governance
    def grant(self, registrars: list[Wallet], to: str, tier: str, note: str = "") -> str:
        """Onboarding grant from the treasury, approved by registrar wallets."""
        tx = T.build(T.GRANT, params.TREASURY_ADDRESS, self.nonce(params.TREASURY_ADDRESS), 0,
                     {"to": to, "tier": tier, "note": note}, self.chain_id)
        for r in registrars:
            r.approve(tx)
        return self.post("/tx", tx)["txid"]

    def registrar_update(self, registrars: list[Wallet], add: list[str] | None = None,
                         remove: list[str] | None = None, threshold: int | None = None) -> str:
        payload = {"add": add or [], "remove": remove or []}
        if threshold is not None:
            payload["threshold"] = threshold
        tx = T.build(T.REGISTRAR_UPDATE, params.TREASURY_ADDRESS, self.nonce(params.TREASURY_ADDRESS), 0, payload, self.chain_id)
        for r in registrars:
            r.approve(tx)
        return self.post("/tx", tx)["txid"]

    # --------------------------------------------------------------- misc
    def mine(self, miner: str, blocks: int = 1) -> dict:
        return self.post("/mine", {"miner": miner, "blocks": blocks})
