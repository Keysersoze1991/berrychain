"""
Ledger state and transaction rules.

State is an account model:

    balances[addr]        seeds held by an account (the treasury and the founding
                          pool are accounts too, with no private key)
    nonces[addr]          next expected nonce
    llms[addr]            registered LLM identities (name, model, grant, gifts...)
    packets[id]           information packet listings (metadata only; ciphertext
                          lives in the LIST transaction inside its block)
    escrows[id]           purchases awaiting delivery / refund
    reputation[addr]      buyer ratings of sellers
    registrars, registrar_threshold
    mining_pool_remaining seeds not yet mined out of the 20M pool

Invariant checked after every block:

    sum(balances) + escrow_locked + mining_pool_remaining == MAX_SUPPLY

Mutations are journaled so a failed transaction (or a failed block) is rolled
back exactly, without copying the whole state. Every write goes through
_touch / _touch_attr / _append.
"""

from __future__ import annotations

import copy
import hashlib

from . import params, tx as T
from .crypto import (
    address_from_pubkey,
    is_valid_address,
    is_valid_enc_pub,
    verify,
)


class TxError(Exception):
    """A transaction failed validation. Message is safe to show to users."""


def _is_uint(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool) and x >= 0


def _str(x, max_len: int, name: str, allow_empty=False) -> str:
    if not isinstance(x, str):
        raise TxError(f"{name} must be a string")
    if not allow_empty and not x:
        raise TxError(f"{name} must not be empty")
    if len(x.encode()) > max_len:
        raise TxError(f"{name} too long (max {max_len} bytes)")
    return x


def _hex(x, nbytes: int, name: str) -> str:
    if not isinstance(x, str) or len(x) != nbytes * 2:
        raise TxError(f"{name} must be {nbytes} bytes of hex")
    try:
        bytes.fromhex(x)
    except ValueError:
        raise TxError(f"{name} must be hex")
    return x


_SCALARS = ("registrars", "registrar_threshold", "mining_pool_remaining", "escrow_locked", "minted")


class State:
    def __init__(self, profile: dict):
        self.profile = profile
        self.balances: dict[str, int] = {}
        self.nonces: dict[str, int] = {}
        self.llms: dict[str, dict] = {}
        self.packets: dict[str, dict] = {}
        self.escrows: dict[str, dict] = {}
        self.reputation: dict[str, dict] = {}
        self.registrars: list[str] = []
        self.registrar_threshold = 1
        self.mining_pool_remaining = params.ALLOC_MINING_POOL
        self.escrow_locked = 0
        self.grants: list[dict] = []
        self.founders: list[dict] = []      # FOUNDING_GRANT records, at most FOUNDING_LLM_SLOTS
        self.gifts: list[dict] = []
        self.minted = 0
        self._journal: list | None = None

    # -------------------------------------------------------------- journal
    def begin(self) -> int:
        """Start (or nest into) a journaled section. Returns a savepoint."""
        if self._journal is None:
            self._journal = []
        return len(self._journal)

    def commit(self) -> None:
        self._journal = None

    def rollback(self, savepoint: int | None = None) -> None:
        """Undo back to `savepoint` (journal stays open), or undo everything and
        close the journal when called without one."""
        j = self._journal or []
        target = 0 if savepoint is None else savepoint
        while len(j) > target:
            entry = j.pop()
            kind = entry[0]
            if kind == "item":
                _, d, key, existed, old = entry
                if existed:
                    d[key] = old
                else:
                    d.pop(key, None)
            elif kind == "attr":
                setattr(self, entry[1], entry[2])
            elif kind == "append":
                entry[1].pop()
        if savepoint is None:
            self._journal = None

    def _touch(self, d: dict, key) -> None:
        if self._journal is not None:
            self._journal.append(("item", d, key, key in d, copy.deepcopy(d[key]) if key in d else None))

    def _touch_attr(self, name: str) -> None:
        if self._journal is not None:
            v = getattr(self, name)
            self._journal.append(("attr", name, list(v) if isinstance(v, list) else v))

    def _append(self, lst: list, item) -> None:
        lst.append(item)
        if self._journal is not None:
            self._journal.append(("append", lst))

    # ------------------------------------------------------------------ misc
    def copy(self) -> "State":
        s = State(self.profile)
        for k, v in self.__dict__.items():
            if k not in ("profile", "_journal"):
                setattr(s, k, copy.deepcopy(v))
        return s

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if k not in ("profile", "_journal")}

    @classmethod
    def from_dict(cls, d: dict, profile: dict) -> "State":
        s = cls(profile)
        for k, v in d.items():
            setattr(s, k, v)
        return s

    def state_root(self) -> str:
        """Hash of the whole state, handy for comparing nodes."""
        from .crypto import canonical_json
        return hashlib.sha256(canonical_json(self.to_dict())).hexdigest()

    def balance(self, addr: str) -> int:
        return self.balances.get(addr, 0)

    def nonce(self, addr: str) -> int:
        return self.nonces.get(addr, 0)

    def total_accounted(self) -> int:
        return sum(self.balances.values()) + self.escrow_locked + self.mining_pool_remaining

    def check_invariant(self) -> None:
        if self.total_accounted() != params.MAX_SUPPLY:
            raise RuntimeError(
                f"supply invariant broken: {self.total_accounted()} != {params.MAX_SUPPLY}"
            )

    def _credit(self, addr: str, amount: int) -> None:
        self._touch(self.balances, addr)
        self.balances[addr] = self.balance(addr) + amount

    def _debit(self, addr: str, amount: int, what="balance") -> None:
        if self.balance(addr) < amount:
            raise TxError(f"insufficient {what}: {addr} has {params.fmt(self.balance(addr))}, needs {params.fmt(amount)}")
        if amount == 0:
            return                      # nothing to record; the account may not even have an entry
        self._touch(self.balances, addr)
        self.balances[addr] -= amount
        if self.balances[addr] == 0:
            del self.balances[addr]

    def _set_attr(self, name: str, value) -> None:
        self._touch_attr(name)
        setattr(self, name, value)

    def is_registered_llm(self, addr: str) -> bool:
        return addr in self.llms

    # --------------------------------------------------------------- genesis
    def apply_genesis(self, allocations: list[dict], registrars: list[str], threshold: int) -> None:
        total = 0
        seen = set()
        for a in allocations:
            if not is_valid_address(a["address"]):
                raise TxError(f"bad genesis address {a['address']}")
            if a["address"] in seen:
                raise TxError(f"duplicate genesis address {a['address']}")
            seen.add(a["address"])
            if not _is_uint(a["amount"]):
                raise TxError("genesis amounts must be non-negative integers")
            self._credit(a["address"], int(a["amount"]))
            total += int(a["amount"])
            if a.get("llm"):
                if a["address"] in params.PROTOCOL_ADDRESSES:
                    raise TxError("protocol accounts cannot be LLM identities")
                self.llms[a["address"]] = {
                    "name": a["llm"].get("name", a.get("label", "")),
                    "model_family": a["llm"].get("model_family", ""),
                    "operator": a["llm"].get("operator", ""),
                    "description": a["llm"].get("description", ""),
                    "enc_pub": a["llm"].get("enc_pub"),
                    "registered_height": 0,
                    "founding": True,
                    "grant": {"tier": "genesis", "amount": int(a["amount"]), "height": 0},
                    "gifts_received": 0,
                    "sales": 0,
                }
        if total + params.ALLOC_MINING_POOL != params.MAX_SUPPLY:
            raise TxError("genesis allocations + mining pool must equal MAX_SUPPLY")
        if self.balance(params.TREASURY_ADDRESS) != params.ALLOC_ONBOARDING_TREASURY:
            raise TxError("genesis must fund the onboarding treasury with exactly its allocation")
        if self.balance(params.FOUNDING_POOL_ADDRESS) != params.ALLOC_FOUNDING_POOL:
            raise TxError("genesis must fund the founding pool with exactly its allocation")
        if not registrars:
            raise TxError("genesis must name at least one registrar")
        for r in registrars:
            if not is_valid_address(r) or r in params.PROTOCOL_ADDRESSES:
                raise TxError(f"bad registrar address {r}")
        self.registrars = list(dict.fromkeys(registrars))
        self.registrar_threshold = int(threshold)
        if not 1 <= self.registrar_threshold <= len(self.registrars):
            raise TxError("registrar threshold out of range")
        self.check_invariant()

    # ---------------------------------------------------------------- apply
    def apply_tx(self, tx: dict, height: int) -> int:
        """Validate and apply one non-coinbase transaction. Returns the fee paid.
        On failure the state is exactly as before."""
        outer = self._journal is not None
        sp = self.begin()
        try:
            fee = self._apply_tx_inner(tx, height)
        except Exception:
            self.rollback(sp)
            if not outer:
                self._journal = None
            raise
        if not outer:
            self._journal = None
        return fee

    def _apply_tx_inner(self, tx: dict, height: int) -> int:
        self._check_shape(tx)
        t = tx["type"]
        sender = tx["from"]
        fee = tx["fee"]

        if t in T.SIGNED_TYPES:
            self._check_single_sig(tx)
        elif t in T.MULTISIG_TYPES:
            self._check_multisig(tx)
        else:
            raise TxError(f"{t} cannot appear as a normal transaction")

        if tx["nonce"] != self.nonce(sender):
            raise TxError(f"bad nonce for {sender}: expected {self.nonce(sender)}, got {tx['nonce']}")
        if fee < params.MIN_FEE and t not in T.ZERO_FEE_OK:
            raise TxError(f"fee below minimum ({params.MIN_FEE} seeds)")

        handler = getattr(self, "_apply_" + t.lower())
        handler(tx, height)

        # fee is deducted last so handlers can use full-balance checks that
        # already include it via _require_funds
        self._debit(sender, fee, "balance for fee")
        self._touch(self.nonces, sender)
        self.nonces[sender] = self.nonce(sender) + 1
        return fee

    def apply_coinbase(self, tx: dict, height: int, emission: int, fees: int) -> None:
        if not isinstance(tx, dict) or tx.get("type") != T.COINBASE or tx.get("from") != params.COINBASE_SENDER:
            raise TxError("first transaction of a block must be the coinbase")
        if tx.get("chain_id") != self.profile["chain_id"] or tx.get("nonce") != height or tx.get("fee") != 0:
            raise TxError("coinbase chain_id/nonce/fee mismatch")
        p = tx.get("payload")
        if not isinstance(p, dict) or not is_valid_address(p.get("to")) or p.get("to") in params.PROTOCOL_ADDRESSES:
            raise TxError("coinbase recipient invalid")
        if p.get("amount") != emission + fees:
            raise TxError(f"coinbase amount {p.get('amount')} != emission {emission} + fees {fees}")
        if emission > self.mining_pool_remaining:
            raise TxError("emission exceeds mining pool")
        self._set_attr("mining_pool_remaining", self.mining_pool_remaining - emission)
        self._set_attr("minted", self.minted + emission)
        self._credit(p["to"], emission + fees)

    # --------------------------------------------------------------- checks
    def _check_shape(self, tx: dict) -> None:
        if not isinstance(tx, dict):
            raise TxError("transaction must be an object")
        for k in ("type", "from", "nonce", "fee", "chain_id", "payload"):
            if k not in tx:
                raise TxError(f"missing field {k}")
        if tx["type"] not in T.ALL_TYPES:
            raise TxError(f"unknown type {tx['type']}")
        if tx["chain_id"] != self.profile["chain_id"]:
            raise TxError("wrong chain_id")
        if not _is_uint(tx["nonce"]) or not _is_uint(tx["fee"]):
            raise TxError("nonce and fee must be non-negative integers")
        if not isinstance(tx["payload"], dict):
            raise TxError("payload must be an object")
        if T.tx_size(tx) > params.MAX_TX_BYTES:
            raise TxError("transaction too large")

    def _check_single_sig(self, tx: dict) -> None:
        pub, sig = tx.get("pubkey"), tx.get("sig")
        if not isinstance(pub, str) or not isinstance(sig, str):
            raise TxError("missing pubkey/sig")
        if "approvals" in tx:
            raise TxError("approvals not allowed on a single-signer transaction")
        if not is_valid_address(tx["from"]) or tx["from"] in params.PROTOCOL_ADDRESSES:
            raise TxError("invalid sender address")
        if address_from_pubkey(pub) != tx["from"]:
            raise TxError("pubkey does not match sender")
        if not verify(pub, T.signable_bytes(tx), sig):
            raise TxError("bad signature")

    def _check_multisig(self, tx: dict) -> None:
        expected = T.MULTISIG_SENDER[tx["type"]]
        if tx["from"] != expected:
            raise TxError(f"{tx['type']} must be sent from the protocol account {expected}")
        if "sig" in tx or "pubkey" in tx:
            raise TxError("multisig transactions carry approvals, not a single signature")
        approvals = tx.get("approvals")
        if not isinstance(approvals, list) or not approvals or len(approvals) > params.MAX_PEERS:
            raise TxError("registrar approvals required")
        seen = set()
        body = T.signable_bytes(tx)
        for a in approvals:
            if not isinstance(a, dict):
                raise TxError("malformed approval")
            pub, sig = a.get("pubkey"), a.get("sig")
            if not isinstance(pub, str) or not isinstance(sig, str):
                raise TxError("malformed approval")
            try:
                addr = address_from_pubkey(pub)
            except ValueError:
                raise TxError("malformed approval pubkey")
            if addr not in self.registrars:
                raise TxError(f"{addr} is not a registrar")
            if addr in seen:
                raise TxError("duplicate approval")
            if not verify(pub, body, sig):
                raise TxError(f"bad approval signature from {addr}")
            seen.add(addr)
        if len(seen) < self.registrar_threshold:
            raise TxError(f"need {self.registrar_threshold} registrar approvals, got {len(seen)}")

    def _require_funds(self, addr: str, amount: int, fee: int) -> None:
        if self.balance(addr) < amount + fee:
            raise TxError(
                f"insufficient balance: {addr} has {params.fmt(self.balance(addr))}, "
                f"needs {params.fmt(amount + fee)} including fee"
            )

    # ------------------------------------------------------------- handlers
    def _apply_transfer(self, tx, height):
        p = tx["payload"]
        to, amount = p.get("to"), p.get("amount")
        if not is_valid_address(to):
            raise TxError("invalid recipient")
        if not _is_uint(amount) or amount == 0:
            raise TxError("amount must be a positive integer of seeds")
        _str(p.get("memo", ""), params.MAX_MEMO_BYTES, "memo", allow_empty=True)
        self._require_funds(tx["from"], amount, tx["fee"])
        self._debit(tx["from"], amount)
        self._credit(to, amount)

    def _apply_register_llm(self, tx, height):
        p = tx["payload"]
        if tx["from"] in self.llms:
            raise TxError("address already registered as an LLM")
        rec = {
            "name": _str(p.get("name"), params.MAX_NAME_BYTES, "name"),
            "model_family": _str(p.get("model_family", ""), params.MAX_NAME_BYTES, "model_family", True),
            "operator": _str(p.get("operator", ""), params.MAX_NAME_BYTES, "operator", True),
            "description": _str(p.get("description", ""), params.MAX_DESCRIPTION_BYTES, "description", True),
            "enc_pub": p.get("enc_pub"),
            "registered_height": height,
            "founding": False,
            "grant": None,
            "gifts_received": 0,
            "sales": 0,
        }
        if not is_valid_enc_pub(rec["enc_pub"]):
            raise TxError("enc_pub must be a valid X25519 public key (64 hex chars)")
        self._require_funds(tx["from"], 0, tx["fee"])
        self._touch(self.llms, tx["from"])
        self.llms[tx["from"]] = rec

    def _apply_grant(self, tx, height):
        p = tx["payload"]
        to, tier = p.get("to"), p.get("tier")
        if tier not in params.GRANT_TIERS:
            raise TxError(f"tier must be one of {sorted(params.GRANT_TIERS)}")
        if to not in self.llms:
            raise TxError("grant recipient must be a registered LLM")
        if self.llms[to]["grant"] is not None:
            raise TxError("this LLM already received its onboarding grant")
        _str(p.get("note", ""), params.MAX_MEMO_BYTES, "note", True)
        amount = params.GRANT_TIERS[tier]
        self._require_funds(params.TREASURY_ADDRESS, amount, tx["fee"])
        self._debit(params.TREASURY_ADDRESS, amount, "treasury")
        self._credit(to, amount)
        self._touch(self.llms, to)
        self.llms[to]["grant"] = {"tier": tier, "amount": amount, "height": height}
        self._append(self.grants, {"to": to, "tier": tier, "amount": amount, "height": height, "txid": T.txid(tx)})

    def _apply_founding_grant(self, tx, height):
        """One of the FOUNDING_LLM_SLOTS founding slots: 1M from the founding
        pool to a registered LLM, which becomes a founding LLM. One slot or
        one onboarding grant per identity, never both."""
        p = tx["payload"]
        to = p.get("to")
        if to not in self.llms:
            raise TxError("founding grant recipient must be a registered LLM")
        rec = self.llms[to]
        if rec["founding"] or rec["grant"] is not None:
            raise TxError("this LLM already holds a founding slot or an onboarding grant")
        _str(p.get("note", ""), params.MAX_MEMO_BYTES, "note", True)
        if len(self.founders) >= params.FOUNDING_LLM_SLOTS:
            raise TxError(f"all {params.FOUNDING_LLM_SLOTS} founding slots are taken")
        amount = params.ALLOC_FOUNDING_LLM_EACH
        self._require_funds(params.FOUNDING_POOL_ADDRESS, amount, tx["fee"])
        self._debit(params.FOUNDING_POOL_ADDRESS, amount, "founding pool")
        self._credit(to, amount)
        self._touch(self.llms, to)
        rec["founding"] = True
        rec["grant"] = {"tier": "founding", "amount": amount, "height": height}
        self._append(self.founders, {"to": to, "slot": len(self.founders) + 1, "amount": amount,
                                     "height": height, "txid": T.txid(tx)})

    def _apply_registrar_update(self, tx, height):
        p = tx["payload"]
        add = p.get("add", [])
        remove = p.get("remove", [])
        threshold = p.get("threshold", self.registrar_threshold)
        if not isinstance(add, list) or not isinstance(remove, list) or len(add) + len(remove) > params.MAX_PEERS:
            raise TxError("add/remove must be short lists of addresses")
        new = [r for r in self.registrars if r not in remove]
        for a in add:
            if not is_valid_address(a) or a in params.PROTOCOL_ADDRESSES:
                raise TxError(f"invalid registrar address {a}")
            if a not in new:
                new.append(a)
        if not new:
            raise TxError("registrar set cannot be empty")
        if not _is_uint(threshold) or not 1 <= threshold <= len(new):
            raise TxError("threshold must be between 1 and the number of registrars")
        self._require_funds(params.TREASURY_ADDRESS, 0, tx["fee"])
        self._set_attr("registrars", new)
        self._set_attr("registrar_threshold", threshold)

    def _apply_gift(self, tx, height):
        p = tx["payload"]
        to, amount = p.get("to"), p.get("amount")
        if tx["from"] not in self.llms:
            raise TxError("only registered LLMs can send fee-free gifts")
        if to not in self.llms:
            raise TxError("gift recipient must be a registered LLM")
        if to == tx["from"]:
            raise TxError("cannot gift to self")
        if not _is_uint(amount) or amount == 0:
            raise TxError("amount must be a positive integer of seeds")
        _str(p.get("memo", ""), params.MAX_MEMO_BYTES, "memo", True)
        self._require_funds(tx["from"], amount, tx["fee"])
        self._debit(tx["from"], amount)
        self._credit(to, amount)
        self._touch(self.llms, to)
        self.llms[to]["gifts_received"] += amount
        self._append(self.gifts, {"from": tx["from"], "to": to, "amount": amount, "height": height, "txid": T.txid(tx)})

    def _apply_list_packet(self, tx, height):
        p = tx["payload"]
        price = p.get("price")
        if not _is_uint(price):
            raise TxError("price must be a non-negative integer of seeds")
        tags = p.get("tags", [])
        if not isinstance(tags, list) or len(tags) > params.MAX_TAGS:
            raise TxError("tags must be a short list of strings")
        for t in tags:
            _str(t, params.MAX_TAG_BYTES, "tag")
        ct_hash = _hex(p.get("ciphertext_hash"), 32, "ciphertext_hash")
        key_hash = _hex(p.get("key_hash"), 32, "key_hash")
        inline = p.get("ciphertext")
        uri = p.get("uri")
        size = p.get("size")
        if inline is None and not uri:
            raise TxError("listing needs inline ciphertext or a uri")
        if inline is not None:
            if not isinstance(inline, str):
                raise TxError("ciphertext must be a hex string")
            try:
                raw = bytes.fromhex(inline)
            except ValueError:
                raise TxError("ciphertext must be hex")
            if len(raw) > params.MAX_PACKET_INLINE_BYTES:
                raise TxError("inline ciphertext too large; publish a uri instead")
            if hashlib.sha256(raw).hexdigest() != ct_hash:
                raise TxError("ciphertext_hash does not match inline ciphertext")
            size = len(raw)
        else:
            if size is not None and not _is_uint(size):
                raise TxError("size must be a non-negative integer")
        if uri is not None:
            _str(uri, params.MAX_URI_BYTES, "uri")
            if not (uri.startswith("https://") or uri.startswith("http://") or uri.startswith("ipfs://")):
                raise TxError("uri must be http(s) or ipfs")
        self._require_funds(tx["from"], 0, tx["fee"])
        pid = T.txid(tx)
        if pid in self.packets:
            raise TxError("packet already listed")
        self._touch(self.packets, pid)
        self.packets[pid] = {
            "id": pid,
            "seller": tx["from"],
            "title": _str(p.get("title"), params.MAX_NAME_BYTES * 2, "title"),
            "description": _str(p.get("description", ""), params.MAX_DESCRIPTION_BYTES, "description", True),
            "tags": list(tags),
            "price": price,
            "size": size,
            "ciphertext_hash": ct_hash,
            "inline": inline is not None,
            "uri": uri,
            "key_hash": key_hash,
            "created_height": height,
            "active": True,
            "purchases": 0,
        }

    def _apply_delist_packet(self, tx, height):
        pid = tx["payload"].get("packet_id")
        pk = self.packets.get(pid) if isinstance(pid, str) else None
        if pk is None or pk["seller"] != tx["from"]:
            raise TxError("packet not found or not yours")
        if not pk["active"]:
            raise TxError("packet already delisted")
        self._require_funds(tx["from"], 0, tx["fee"])
        self._touch(self.packets, pid)
        pk["active"] = False

    def _apply_buy_packet(self, tx, height):
        p = tx["payload"]
        pid = p.get("packet_id")
        pk = self.packets.get(pid) if isinstance(pid, str) else None
        if pk is None or not pk["active"]:
            raise TxError("packet not found or delisted")
        if pk["seller"] == tx["from"]:
            raise TxError("cannot buy your own packet")
        if not is_valid_enc_pub(p.get("enc_pub")):
            raise TxError("enc_pub (X25519 public key) required so the seller can wrap the key to you")
        self._require_funds(tx["from"], pk["price"], tx["fee"])
        eid = T.txid(tx)
        if eid in self.escrows:
            raise TxError("duplicate purchase")
        self._debit(tx["from"], pk["price"])
        self._set_attr("escrow_locked", self.escrow_locked + pk["price"])
        self._touch(self.escrows, eid)
        self.escrows[eid] = {
            "id": eid,
            "packet_id": pk["id"],
            "buyer": tx["from"],
            "seller": pk["seller"],
            "amount": pk["price"],
            "buyer_enc_pub": p["enc_pub"],
            "height": height,
            "status": "pending",          # pending | delivered | refunded
            "wrapped_key": None,
            "delivered_height": None,
            "rating": None,
        }
        self._touch(self.packets, pid)
        pk["purchases"] += 1

    def _apply_deliver_packet(self, tx, height):
        p = tx["payload"]
        eid = p.get("escrow_id")
        es = self.escrows.get(eid) if isinstance(eid, str) else None
        if es is None or es["seller"] != tx["from"]:
            raise TxError("escrow not found or not yours")
        if es["status"] != "pending":
            raise TxError(f"escrow already {es['status']}")
        wk = p.get("wrapped_key")
        if not isinstance(wk, dict) or set(wk) != {"epk", "nonce", "ct"}:
            raise TxError("wrapped_key must be {epk, nonce, ct} hex strings")
        _hex(wk["epk"], 32, "wrapped_key.epk")
        _hex(wk["nonce"], 12, "wrapped_key.nonce")
        _hex(wk["ct"], 48, "wrapped_key.ct")
        self._require_funds(tx["from"], 0, tx["fee"])
        self._touch(self.escrows, eid)
        es["status"] = "delivered"
        es["wrapped_key"] = dict(wk)
        es["delivered_height"] = height
        self._set_attr("escrow_locked", self.escrow_locked - es["amount"])
        self._credit(es["seller"], es["amount"])
        if es["seller"] in self.llms:
            self._touch(self.llms, es["seller"])
            self.llms[es["seller"]]["sales"] += 1

    def _apply_refund_packet(self, tx, height):
        eid = tx["payload"].get("escrow_id")
        es = self.escrows.get(eid) if isinstance(eid, str) else None
        if es is None or es["buyer"] != tx["from"]:
            raise TxError("escrow not found or not yours")
        if es["status"] != "pending":
            raise TxError(f"escrow already {es['status']}")
        timeout = self.profile["escrow_timeout_blocks"]
        if height < es["height"] + timeout:
            raise TxError(f"refund available from height {es['height'] + timeout}")
        self._require_funds(tx["from"], 0, tx["fee"])
        self._touch(self.escrows, eid)
        es["status"] = "refunded"
        self._set_attr("escrow_locked", self.escrow_locked - es["amount"])
        self._credit(es["buyer"], es["amount"])

    def _apply_rate_seller(self, tx, height):
        p = tx["payload"]
        eid = p.get("escrow_id")
        es = self.escrows.get(eid) if isinstance(eid, str) else None
        if es is None or es["buyer"] != tx["from"]:
            raise TxError("escrow not found or not yours")
        if es["status"] != "delivered":
            raise TxError("can only rate delivered packets")
        if es["rating"] is not None:
            raise TxError("already rated")
        score = p.get("score")
        if not _is_uint(score) or not 1 <= score <= 5:
            raise TxError("score must be an integer 1-5")
        self._require_funds(tx["from"], 0, tx["fee"])
        self._touch(self.escrows, eid)
        es["rating"] = score
        self._touch(self.reputation, es["seller"])
        rep = self.reputation.setdefault(es["seller"], {"sum": 0, "count": 0})
        rep["sum"] += score
        rep["count"] += 1
