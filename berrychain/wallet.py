"""
A wallet file holds one identity: a signing key (Ed25519, gives the address),
an encryption key (X25519, used to receive packet keys) and the packet keys
this identity has listed for sale.

Plaintext form (the default for throwaway devnet keys):

    {
      "label": "architect",
      "address": "brry1...",
      "sign_priv": "...", "sign_pub": "...",
      "enc_priv": "...",  "enc_pub": "...",
      "packet_keys": {"<packet_id>": "<hex key>"}
    }

Encrypted form (use it for anything that holds value): the public fields
stay readable, the secrets are sealed under a passphrase with scrypt +
ChaCha20-Poly1305.

    {
      "label": "architect", "address": "brry1...", "sign_pub": "...", "enc_pub": "...",
      "encrypted": {"kdf": "scrypt", "n": 32768, "r": 8, "p": 1,
                    "salt": "...", "nonce": "...", "ct": "..."}
    }

Whoever holds the file *and* the passphrase controls the coins. A wallet is
unlocked with an explicit passphrase, the BERRY_WALLET_PASSPHRASE environment
variable, or an interactive prompt when a terminal is attached.
"""

from __future__ import annotations

import getpass
import json
import os
import sys

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from . import crypto, tx as T

PASSPHRASE_ENV = "BERRY_WALLET_PASSPHRASE"
SCRYPT_N, SCRYPT_R, SCRYPT_P = 1 << 15, 8, 1          # ~32 MB, ~0.1 s on a laptop
_SECRET_FIELDS = ("sign_priv", "enc_priv", "packet_keys")
_AAD = b"berry-wallet-v1"


class WalletLocked(Exception):
    """The wallet is encrypted and no valid passphrase was supplied."""


def _derive(passphrase: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return Scrypt(salt=salt, length=32, n=n, r=r, p=p).derive(passphrase.encode("utf-8"))


def seal(secrets: dict, passphrase: str) -> dict:
    if not passphrase:
        raise ValueError("passphrase must not be empty")
    salt, nonce = os.urandom(16), os.urandom(12)
    key = _derive(passphrase, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
    ct = ChaCha20Poly1305(key).encrypt(nonce, crypto.canonical_json(secrets), _AAD)
    return {"kdf": "scrypt", "n": SCRYPT_N, "r": SCRYPT_R, "p": SCRYPT_P,
            "salt": salt.hex(), "nonce": nonce.hex(), "ct": ct.hex()}


def unseal(blob: dict, passphrase: str) -> dict:
    if blob.get("kdf") != "scrypt":
        raise WalletLocked(f"unsupported wallet kdf {blob.get('kdf')!r}")
    key = _derive(passphrase, bytes.fromhex(blob["salt"]), int(blob["n"]), int(blob["r"]), int(blob["p"]))
    try:
        pt = ChaCha20Poly1305(key).decrypt(bytes.fromhex(blob["nonce"]), bytes.fromhex(blob["ct"]), _AAD)
    except InvalidTag:
        raise WalletLocked("wrong passphrase") from None
    return json.loads(pt)


def _resolve_passphrase(passphrase: str | None, path: str | None, confirm: bool = False, interactive: bool | None = None) -> str:
    """Explicit argument, then environment, then an interactive prompt."""
    if passphrase:
        return passphrase
    env = os.environ.get(PASSPHRASE_ENV)
    if env:
        return env
    if interactive is None:
        interactive = sys.stdin is not None and sys.stdin.isatty()
    if interactive:
        what = os.path.basename(path) if path else "wallet"
        p = getpass.getpass(f"passphrase for {what}: ")
        if confirm and getpass.getpass("again: ") != p:
            raise WalletLocked("passphrases did not match")
        if not p:
            raise WalletLocked("empty passphrase")
        return p
    raise WalletLocked(f"wallet {path or ''} is encrypted; set {PASSPHRASE_ENV} or pass a passphrase")


class Wallet:
    def __init__(self, d: dict, path: str | None = None, passphrase: str | None = None, interactive: bool | None = None):
        self.label = d.get("label", "")
        self.path = path
        self.passphrase: str | None = None            # remembered so saves stay encrypted
        if "encrypted" in d:
            self.passphrase = _resolve_passphrase(passphrase, path, interactive=interactive)
            secrets = unseal(d["encrypted"], self.passphrase)
            d = {**d, **secrets}
        self.sign_priv = d["sign_priv"]
        self.sign_pub = d.get("sign_pub") or crypto.public_from_private(self.sign_priv)
        self.enc_priv = d["enc_priv"]
        self.enc_pub = d.get("enc_pub") or crypto.encryption_public_from_private(self.enc_priv)
        self.address = crypto.address_from_pubkey(self.sign_pub)
        self.packet_keys: dict[str, str] = dict(d.get("packet_keys", {}))

    # ------------------------------------------------------------ files
    @classmethod
    def create(cls, label: str = "", passphrase: str | None = None) -> "Wallet":
        sp, spub = crypto.generate_signing_keypair()
        ep, epub = crypto.generate_encryption_keypair()
        w = cls({"label": label, "sign_priv": sp, "sign_pub": spub, "enc_priv": ep, "enc_pub": epub})
        w.passphrase = passphrase or None
        return w

    @classmethod
    def load(cls, path: str, passphrase: str | None = None, interactive: bool | None = None) -> "Wallet":
        """`interactive=False` never prompts (servers, tests); None means prompt only on a terminal."""
        with open(path) as f:
            return cls(json.load(f), path, passphrase, interactive)

    @staticmethod
    def read_public(path: str) -> dict:
        """Public fields of a wallet file, no passphrase needed even if encrypted."""
        with open(path) as f:
            d = json.load(f)
        if "encrypted" in d:
            return {"label": d.get("label", ""), "address": d["address"], "sign_pub": d["sign_pub"],
                    "enc_pub": d["enc_pub"], "encrypted": True}
        w = Wallet(d)
        return {**w.public_info(), "encrypted": False}

    @staticmethod
    def is_encrypted(path: str) -> bool:
        with open(path) as f:
            return "encrypted" in json.load(f)

    def to_dict(self) -> dict:
        pub = {"label": self.label, "address": self.address, "sign_pub": self.sign_pub, "enc_pub": self.enc_pub}
        secrets = {"sign_priv": self.sign_priv, "enc_priv": self.enc_priv, "packet_keys": self.packet_keys}
        if self.passphrase:
            return {**pub, "encrypted": seal(secrets, self.passphrase)}
        return {**pub, **secrets}

    def public_info(self) -> dict:
        return {"label": self.label, "address": self.address, "sign_pub": self.sign_pub, "enc_pub": self.enc_pub}

    def encrypt(self, passphrase: str) -> None:
        """Seal this wallet under `passphrase` on its next save."""
        if not passphrase:
            raise ValueError("passphrase must not be empty")
        self.passphrase = passphrase

    def save(self, path: str | None = None) -> None:
        path = path or self.path
        if not path:
            raise ValueError("no path to save wallet to")
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
        os.replace(tmp, path)
        self.path = path

    # convenience wrappers
    def sign(self, tx: dict) -> dict:
        return T.sign_tx(tx, self.sign_priv)

    def approve(self, tx: dict) -> dict:
        return T.add_approval(tx, self.sign_priv)
