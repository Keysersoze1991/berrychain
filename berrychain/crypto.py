"""
Cryptographic primitives for BerryChain.

* Ed25519 for account signatures
* X25519 + HKDF + ChaCha20-Poly1305 for wrapping packet keys to a buyer
* ChaCha20-Poly1305 for encrypting packet contents
* SHA-256 for hashing, addresses and proof-of-work
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from . import params

ADDRESS_PREFIX = "brry1"
_RAW = serialization.Encoding.Raw
_PUB_RAW = serialization.PublicFormat.Raw
_PRIV_RAW = serialization.PrivateFormat.Raw
_NOENC = serialization.NoEncryption()


# ---------------------------------------------------------------------------
# Hashing / canonical encoding
# ---------------------------------------------------------------------------

def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def sha256d(data: bytes) -> bytes:
    return sha256(sha256(data))


def canonical_json(obj: Any) -> bytes:
    """Deterministic JSON encoding used for every hash and signature."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def hash_obj(obj: Any) -> str:
    return sha256(canonical_json(obj)).hex()


# ---------------------------------------------------------------------------
# Signing keys and addresses
# ---------------------------------------------------------------------------

def generate_signing_keypair() -> tuple[str, str]:
    """Return (private_hex, public_hex) for a new Ed25519 key."""
    priv = Ed25519PrivateKey.generate()
    priv_hex = priv.private_bytes(_RAW, _PRIV_RAW, _NOENC).hex()
    pub_hex = priv.public_key().public_bytes(_RAW, _PUB_RAW).hex()
    return priv_hex, pub_hex


def public_from_private(priv_hex: str) -> str:
    priv = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(priv_hex))
    return priv.public_key().public_bytes(_RAW, _PUB_RAW).hex()


def sign(priv_hex: str, message: bytes) -> str:
    priv = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(priv_hex))
    return priv.sign(message).hex()


def verify(pub_hex: str, message: bytes, sig_hex: str) -> bool:
    try:
        pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(pub_hex))
        pub.verify(bytes.fromhex(sig_hex), message)
        return True
    except (InvalidSignature, ValueError):
        return False


def address_from_pubkey(pub_hex: str) -> str:
    payload = sha256(bytes.fromhex(pub_hex))[:20]
    checksum = sha256(b"berry-address" + payload)[:4]
    return ADDRESS_PREFIX + (payload + checksum).hex()


def is_valid_address(addr: Any) -> bool:
    if addr == params.TREASURY_ADDRESS:
        return True
    if not isinstance(addr, str) or not addr.startswith(ADDRESS_PREFIX):
        return False
    body = addr[len(ADDRESS_PREFIX):]
    if len(body) != 48:
        return False
    try:
        raw = bytes.fromhex(body)
    except ValueError:
        return False
    payload, checksum = raw[:20], raw[20:]
    return sha256(b"berry-address" + payload)[:4] == checksum


# ---------------------------------------------------------------------------
# Encryption keys (X25519) and key wrapping
# ---------------------------------------------------------------------------

def generate_encryption_keypair() -> tuple[str, str]:
    priv = X25519PrivateKey.generate()
    return (
        priv.private_bytes(_RAW, _PRIV_RAW, _NOENC).hex(),
        priv.public_key().public_bytes(_RAW, _PUB_RAW).hex(),
    )


def encryption_public_from_private(priv_hex: str) -> str:
    priv = X25519PrivateKey.from_private_bytes(bytes.fromhex(priv_hex))
    return priv.public_key().public_bytes(_RAW, _PUB_RAW).hex()


def is_valid_enc_pub(pub: Any) -> bool:
    if not isinstance(pub, str) or len(pub) != 64:
        return False
    try:
        X25519PublicKey.from_public_bytes(bytes.fromhex(pub))
        return True
    except ValueError:
        return False


def _derive(shared: bytes, epk: bytes, rpk: bytes) -> bytes:
    return HKDF(algorithm=SHA256(), length=32, salt=epk + rpk, info=b"berry-ecies-v1").derive(shared)


def wrap_to_recipient(recipient_pub_hex: str, plaintext: bytes) -> dict:
    """ECIES: encrypt `plaintext` so only the holder of the recipient key can read it."""
    rpk = X25519PublicKey.from_public_bytes(bytes.fromhex(recipient_pub_hex))
    eph = X25519PrivateKey.generate()
    epk_bytes = eph.public_key().public_bytes(_RAW, _PUB_RAW)
    key = _derive(eph.exchange(rpk), epk_bytes, bytes.fromhex(recipient_pub_hex))
    nonce = os.urandom(12)
    ct = ChaCha20Poly1305(key).encrypt(nonce, plaintext, epk_bytes)
    return {"epk": epk_bytes.hex(), "nonce": nonce.hex(), "ct": ct.hex()}


def unwrap_from_sender(recipient_priv_hex: str, blob: dict) -> bytes:
    priv = X25519PrivateKey.from_private_bytes(bytes.fromhex(recipient_priv_hex))
    rpk_bytes = priv.public_key().public_bytes(_RAW, _PUB_RAW)
    epk_bytes = bytes.fromhex(blob["epk"])
    key = _derive(priv.exchange(X25519PublicKey.from_public_bytes(epk_bytes)), epk_bytes, rpk_bytes)
    return ChaCha20Poly1305(key).decrypt(bytes.fromhex(blob["nonce"]), bytes.fromhex(blob["ct"]), epk_bytes)


# ---------------------------------------------------------------------------
# Packet content encryption
# ---------------------------------------------------------------------------

def new_packet_key() -> bytes:
    return os.urandom(32)


def encrypt_packet(key: bytes, plaintext: bytes) -> bytes:
    nonce = os.urandom(12)
    return nonce + ChaCha20Poly1305(key).encrypt(nonce, plaintext, b"berry-packet-v1")


def decrypt_packet(key: bytes, ciphertext: bytes) -> bytes:
    nonce, ct = ciphertext[:12], ciphertext[12:]
    return ChaCha20Poly1305(key).decrypt(nonce, ct, b"berry-packet-v1")


def key_commitment(key: bytes) -> str:
    """Hash published in a listing; lets a buyer check the delivered key is the listed one."""
    return sha256(b"berry-key-commit" + key).hex()
