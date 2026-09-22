"""
Transaction construction and signing.

A transaction is a plain dict so it serialises to JSON without ceremony:

    {
      "type":     "TRANSFER",
      "from":     "brry1...",
      "nonce":    3,                # per-account, strictly sequential
      "fee":      10000,            # seeds, paid to the block producer
      "chain_id": "berry-1",
      "payload":  {...},            # type specific
      "pubkey":   "...",            # single-signer types
      "sig":      "...",
      "approvals": [{"pubkey","sig"}, ...]   # registrar multisig types
    }

The txid is the SHA-256 of the canonical JSON of everything except the
signature fields, so it is known before signing.
"""

from __future__ import annotations

from . import params
from .crypto import (
    address_from_pubkey,
    canonical_json,
    public_from_private,
    sha256,
    sign,
)

# Single-signer transaction types
TRANSFER = "TRANSFER"
REGISTER_LLM = "REGISTER_LLM"
GIFT = "GIFT"
LIST_PACKET = "LIST_PACKET"
DELIST_PACKET = "DELIST_PACKET"
BUY_PACKET = "BUY_PACKET"
DELIVER_PACKET = "DELIVER_PACKET"
REFUND_PACKET = "REFUND_PACKET"
RATE_SELLER = "RATE_SELLER"

# Registrar multisig types (sender is the onboarding treasury)
GRANT = "GRANT"
REGISTRAR_UPDATE = "REGISTRAR_UPDATE"

# System types (no signature; validity comes from block rules)
COINBASE = "COINBASE"
GENESIS = "GENESIS"

SIGNED_TYPES = {
    TRANSFER, REGISTER_LLM, GIFT, LIST_PACKET, DELIST_PACKET,
    BUY_PACKET, DELIVER_PACKET, REFUND_PACKET, RATE_SELLER,
}
MULTISIG_TYPES = {GRANT, REGISTRAR_UPDATE}
SYSTEM_TYPES = {COINBASE, GENESIS}
ALL_TYPES = SIGNED_TYPES | MULTISIG_TYPES | SYSTEM_TYPES

# Types that may carry a zero fee (governance and LLM-to-LLM gifting)
ZERO_FEE_OK = {GIFT, GRANT, REGISTRAR_UPDATE}

_SIG_FIELDS = ("sig", "pubkey", "approvals")


def signable_body(tx: dict) -> dict:
    return {k: v for k, v in tx.items() if k not in _SIG_FIELDS}


def signable_bytes(tx: dict) -> bytes:
    return canonical_json(signable_body(tx))


def txid(tx: dict) -> str:
    return sha256(signable_bytes(tx)).hex()


def tx_size(tx: dict) -> int:
    return len(canonical_json(tx))


def build(tx_type: str, sender: str, nonce: int, fee: int, payload: dict, chain_id: str) -> dict:
    return {
        "type": tx_type,
        "from": sender,
        "nonce": int(nonce),
        "fee": int(fee),
        "chain_id": chain_id,
        "payload": payload,
    }


def sign_tx(tx: dict, priv_hex: str) -> dict:
    """Attach pubkey + signature for a single-signer transaction."""
    pub = public_from_private(priv_hex)
    if address_from_pubkey(pub) != tx["from"]:
        raise ValueError("private key does not match the sender address")
    tx["pubkey"] = pub
    tx["sig"] = sign(priv_hex, signable_bytes(tx))
    return tx


def add_approval(tx: dict, priv_hex: str) -> dict:
    """Add one registrar approval to a multisig (treasury) transaction."""
    pub = public_from_private(priv_hex)
    approvals = tx.setdefault("approvals", [])
    if any(a["pubkey"] == pub for a in approvals):
        return tx
    approvals.append({"pubkey": pub, "sig": sign(priv_hex, signable_bytes(tx))})
    return tx


def coinbase(height: int, miner: str, amount: int, chain_id: str) -> dict:
    return build(COINBASE, params.COINBASE_SENDER, height, 0, {"to": miner, "amount": int(amount)}, chain_id)
