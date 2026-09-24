"""Cross-implementation test vectors for the Flutter app, produced by the
reference Python code. Run from the repository root:

    python app/tool/make_vectors.py

Writes app/test/vectors.json. Every value the Dart core reproduces (canonical
JSON, txids, addresses, signatures, key wrapping, packet encryption, wallet
sealing, merkle roots, block hashes) is checked against these in
app/test/core_test.dart, so the phone and the chain can never disagree."""

import hashlib
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from berrychain import block as B, crypto, params, tx as T  # noqa: E402
from berrychain import wallet as W  # noqa: E402

# fixed keys so the vectors are stable
SIGN_PRIV = "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
ENC_PRIV = "77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a"
ENC_PRIV_2 = "5dab087e624a8a4b79e17f8b83800ee66f3bb1292618b6fd1c2f8b27ff88e0eb"

sign_pub = crypto.public_from_private(SIGN_PRIV)
enc_pub = crypto.encryption_public_from_private(ENC_PRIV)
enc_pub_2 = crypto.encryption_public_from_private(ENC_PRIV_2)
address = crypto.address_from_pubkey(sign_pub)

v = {"sign_priv": SIGN_PRIV, "sign_pub": sign_pub, "address": address,
     "enc_priv": ENC_PRIV, "enc_pub": enc_pub, "enc_priv_2": ENC_PRIV_2, "enc_pub_2": enc_pub_2,
     "treasury": params.TREASURY_ADDRESS, "founding_pool": params.FOUNDING_POOL_ADDRESS}

# canonical json: nesting, unicode, escapes, key order, big ints
obj = {"z": [1, 2, {"b": None, "a": True}], "a": "café ☃ \"q\" \\ / \n\t", "m": 120_000_000 * 100_000_000, "e": {}, "l": []}
v["canonical"] = {"obj": obj, "bytes_hex": crypto.canonical_json(obj).hex(), "sha256": crypto.sha256(crypto.canonical_json(obj)).hex()}

# a signed transfer
tx = T.build(T.TRANSFER, address, 3, params.MIN_FEE, {"to": params.TREASURY_ADDRESS, "amount": 123456789, "memo": "vector"}, params.CHAIN_ID)
T.sign_tx(tx, SIGN_PRIV)
v["transfer"] = {"tx": tx, "txid": T.txid(tx), "signable_hex": T.signable_bytes(tx).hex()}

# a claim with a small work requirement, ground the same way the client does
claim = T.build(T.CLAIM_STARTER, address, 0, params.MIN_FEE,
                {"name": "vector", "kind": "person", "model_family": "", "operator": "", "description": "", "enc_pub": enc_pub, "work_nonce": 0},
                params.CHAIN_ID)
bits = 12
n = 0
while int(T.txid(dict(claim, payload=dict(claim["payload"], work_nonce=n))), 16) >> (256 - bits):
    n += 1
claim["payload"]["work_nonce"] = n
T.sign_tx(claim, SIGN_PRIV)
v["claim"] = {"tx": claim, "txid": T.txid(claim), "work_bits": bits}

# key wrapping and packet encryption, with the randomness fixed by recording outputs
key = bytes.fromhex("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f")
wrapped = crypto.wrap_to_recipient(enc_pub_2, key)
assert crypto.unwrap_from_sender(ENC_PRIV_2, wrapped) == key
ct = crypto.encrypt_packet(key, b"the tide turns at six")
v["packet"] = {"key_hex": key.hex(), "plaintext": "the tide turns at six", "ciphertext_hex": ct.hex(),
               "ciphertext_sha256": hashlib.sha256(ct).hexdigest(), "key_commitment": crypto.key_commitment(key),
               "wrapped_to_2": wrapped}

# a sealed wallet file, exactly as the CLI writes it
secrets = {"sign_priv": SIGN_PRIV, "enc_priv": ENC_PRIV, "packet_keys": {"aa" * 32: key.hex()}}
sealed = W.seal(secrets, "correct horse")
v["wallet"] = {"passphrase": "correct horse", "file": {"label": "vector", "address": address, "sign_pub": sign_pub, "enc_pub": enc_pub, "encrypted": sealed},
               "secrets": secrets}

# real mainnet blocks: genesis and the first two, from a seed
def get(path):
    with urllib.request.urlopen("https://seed1.berrychain.link" + path, timeout=20) as r:
        return json.load(r)

b0, b1 = get("/block/0"), get("/block/1")
hdrs = get("/headers?from=0&to=2")["headers"]
for b in (b0, b1):
    assert B.merkle_root([T.txid(t) for t in b["txs"]]) == b["merkle_root"]
    assert B.block_hash(b) == b["hash"]
v["mainnet"] = {"chain_id": params.CHAIN_ID, "genesis_hash": b0["hash"], "block0": b0, "block1": b1, "headers": hdrs,
                "max_target_hex": B.target_to_hex(params.MAX_TARGET), "work_0_2": B.work_for_target(B.hex_to_target(hdrs[1]["target"])) + B.work_for_target(B.hex_to_target(hdrs[2]["target"]))}
v["merkle"] = {"three": B.merkle_root(["11" * 32, "22" * 32, "33" * 32]), "empty": B.merkle_root([])}

out = os.path.join(ROOT, "app", "test", "vectors.json")
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w", encoding="utf-8") as f:
    json.dump(v, f, indent=1, sort_keys=True)
print("wrote", out, os.path.getsize(out), "bytes")
