"""
Block structure, merkle root, and SHA-256d proof-of-work.

    {
      "height": 12,
      "prev_hash": "...",
      "timestamp": 1758500000,
      "target": "0000ffff...",      # 64 hex chars; hash must be < target
      "merkle_root": "...",
      "nonce": 48213,
      "txs": [...],
      "hash": "..."
    }
"""

from __future__ import annotations

from .crypto import sha256, sha256d
from .tx import txid


def merkle_root(txids: list[str]) -> str:
    if not txids:
        return "00" * 32
    layer = [bytes.fromhex(t) for t in txids]
    while len(layer) > 1:
        if len(layer) % 2 == 1:
            layer.append(layer[-1])
        layer = [sha256(layer[i] + layer[i + 1]) for i in range(0, len(layer), 2)]
    return layer[0].hex()


def header_bytes(height: int, prev_hash: str, timestamp: int, target: str, root: str, nonce: int) -> bytes:
    return f"berry|{height}|{prev_hash}|{timestamp}|{target}|{root}|{nonce}".encode()


def block_hash(block: dict) -> str:
    return sha256d(header_bytes(
        block["height"], block["prev_hash"], block["timestamp"],
        block["target"], block["merkle_root"], block["nonce"],
    )).hex()


def target_to_hex(target: int) -> str:
    return f"{target:064x}"


def hex_to_target(h: str) -> int:
    return int(h, 16)


def work_for_target(target: int) -> int:
    """Expected number of hashes to find a block at this target."""
    return (1 << 256) // (target + 1)


def make_block(height: int, prev_hash: str, timestamp: int, target: int, txs: list[dict], nonce: int = 0) -> dict:
    block = {
        "height": height,
        "prev_hash": prev_hash,
        "timestamp": int(timestamp),
        "target": target_to_hex(target),
        "merkle_root": merkle_root([txid(t) for t in txs]),
        "nonce": nonce,
        "txs": txs,
    }
    block["hash"] = block_hash(block)
    return block


def pow_ok(block: dict) -> bool:
    return int(block["hash"], 16) < hex_to_target(block["target"])


def mine(block: dict, max_iters: int | None = None, should_stop=None) -> bool:
    """Search nonces until the header hash is below target. Mutates the block."""
    target = hex_to_target(block["target"])
    prefix = f"berry|{block['height']}|{block['prev_hash']}|{block['timestamp']}|{block['target']}|{block['merkle_root']}|".encode()
    nonce = block["nonce"]
    i = 0
    while True:
        h = sha256d(prefix + str(nonce).encode())
        if int.from_bytes(h, "big") < target:
            block["nonce"] = nonce
            block["hash"] = h.hex()
            return True
        nonce += 1
        i += 1
        if max_iters is not None and i >= max_iters:
            block["nonce"] = nonce
            return False
        if should_stop is not None and (i & 0x3FF) == 0 and should_stop():
            block["nonce"] = nonce
            return False
