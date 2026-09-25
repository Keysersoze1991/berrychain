"""
Recovery phrases: twelve English words from which a whole wallet is derived,
so a wallet can be rebuilt on any phone or PC from the words alone.

Encoding is BIP-39 (16 bytes of entropy, 4-bit checksum, 12 words from the
standard 2048-word English list) and the seed is the BIP-39 seed
(PBKDF2-HMAC-SHA512, 2048 rounds, salt "mnemonic"). From that 64-byte seed
the two wallet keys are drawn with HKDF-SHA256:

    sign_priv = HKDF(seed, info="berry-sign-v1")     Ed25519 seed, the address
    enc_priv  = HKDF(seed, info="berry-enc-v1")      X25519, receives letters

The phone app derives exactly the same bytes (app/lib/core/mnemonic.dart),
checked against shared vectors.
"""

from __future__ import annotations

import hashlib
import os
import unicodedata

from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_WORDS: list[str] | None = None
_INDEX: dict[str, int] | None = None


def wordlist() -> list[str]:
    global _WORDS, _INDEX
    if _WORDS is None:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "wordlist_en.txt"), encoding="utf-8") as f:
            _WORDS = f.read().split()
        assert len(_WORDS) == 2048
        _INDEX = {w: i for i, w in enumerate(_WORDS)}
    return _WORDS


def _index() -> dict[str, int]:
    wordlist()
    return _INDEX  # type: ignore[return-value]


def new_phrase(entropy: bytes | None = None) -> str:
    """Twelve words from 16 bytes of entropy (fresh if not given)."""
    ent = entropy if entropy is not None else os.urandom(16)
    if len(ent) != 16:
        raise ValueError("entropy must be 16 bytes")
    words = wordlist()
    bits = bin(int.from_bytes(ent, "big"))[2:].zfill(128) + bin(hashlib.sha256(ent).digest()[0])[2:].zfill(8)[:4]
    return " ".join(words[int(bits[i:i + 11], 2)] for i in range(0, 132, 11))


def normalize(phrase: str) -> str:
    return " ".join(unicodedata.normalize("NFKD", phrase).lower().split())


def validate(phrase: str) -> str:
    """Return the normalized phrase, or raise ValueError with a plain reason."""
    words = normalize(phrase).split()
    if len(words) != 12:
        raise ValueError(f"a recovery phrase has 12 words, this has {len(words)}")
    idx = _index()
    bad = [w for w in words if w not in idx]
    if bad:
        raise ValueError(f"not in the word list: {', '.join(bad[:3])}")
    bits = "".join(bin(idx[w])[2:].zfill(11) for w in words)
    ent = int(bits[:128], 2).to_bytes(16, "big")
    if bits[128:] != bin(hashlib.sha256(ent).digest()[0])[2:].zfill(8)[:4]:
        raise ValueError("the words do not check out; one is probably wrong or out of order")
    return " ".join(words)


def seed_from_phrase(phrase: str) -> bytes:
    words = validate(phrase)
    return hashlib.pbkdf2_hmac("sha512", words.encode("utf-8"), b"mnemonic", 2048, dklen=64)


def _hkdf(seed: bytes, info: bytes) -> bytes:
    return HKDF(algorithm=SHA256(), length=32, salt=None, info=info).derive(seed)


def keys_from_phrase(phrase: str) -> tuple[str, str]:
    """(sign_priv_hex, enc_priv_hex) for a phrase."""
    seed = seed_from_phrase(phrase)
    return _hkdf(seed, b"berry-sign-v1").hex(), _hkdf(seed, b"berry-enc-v1").hex()
