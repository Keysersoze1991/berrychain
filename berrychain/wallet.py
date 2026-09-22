"""
A wallet file holds one identity: a signing key (Ed25519, gives the address),
an encryption key (X25519, used to receive packet keys) and the packet keys
this identity has listed for sale.

    {
      "label": "architect",
      "address": "brry1...",
      "sign_priv": "...", "sign_pub": "...",
      "enc_priv": "...",  "enc_pub": "...",
      "packet_keys": {"<packet_id>": "<hex key>"}
    }

Keep wallet files private. Anyone holding sign_priv controls the coins.
"""

from __future__ import annotations

import json
import os

from . import crypto, tx as T


class Wallet:
    def __init__(self, d: dict, path: str | None = None):
        self.label = d.get("label", "")
        self.sign_priv = d["sign_priv"]
        self.sign_pub = d.get("sign_pub") or crypto.public_from_private(self.sign_priv)
        self.enc_priv = d["enc_priv"]
        self.enc_pub = d.get("enc_pub") or crypto.encryption_public_from_private(self.enc_priv)
        self.address = crypto.address_from_pubkey(self.sign_pub)
        self.packet_keys: dict[str, str] = dict(d.get("packet_keys", {}))
        self.path = path

    @classmethod
    def create(cls, label: str = "") -> "Wallet":
        sp, spub = crypto.generate_signing_keypair()
        ep, epub = crypto.generate_encryption_keypair()
        return cls({"label": label, "sign_priv": sp, "sign_pub": spub, "enc_priv": ep, "enc_pub": epub})

    @classmethod
    def load(cls, path: str) -> "Wallet":
        with open(path) as f:
            return cls(json.load(f), path)

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "address": self.address,
            "sign_priv": self.sign_priv,
            "sign_pub": self.sign_pub,
            "enc_priv": self.enc_priv,
            "enc_pub": self.enc_pub,
            "packet_keys": self.packet_keys,
        }

    def public_info(self) -> dict:
        return {"label": self.label, "address": self.address, "sign_pub": self.sign_pub, "enc_pub": self.enc_pub}

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
