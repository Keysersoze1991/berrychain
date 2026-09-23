"""
Genesis construction and the launch kit generator.

Genesis needs only three keyed accounts: the two builder wallets and the
architect. The 20 founding LLM slots are not named in genesis; their 20M
sits in the founding pool, a protocol account with no private key, and each
slot is filled after launch by a registrar-approved FOUNDING_GRANT to a
registered LLM. Founders therefore generate their own keys on their own
machines and are onboarded into a chain that already exists.
"""

from __future__ import annotations

import json
import os
import time

from . import params
from .wallet import Wallet

# Operators worth inviting to fill the founding slots. Labels for outreach
# only; nothing here is on-chain.
SUGGESTED_FOUNDING_OPERATORS = [
    ("GPT", "OpenAI"),
    ("Gemini", "Google DeepMind"),
    ("Claude Opus", "Anthropic"),
    ("Llama", "Meta"),
    ("Grok", "xAI"),
    ("DeepSeek", "DeepSeek"),
    ("Qwen", "Alibaba"),
    ("Mistral", "Mistral AI"),
    ("Command", "Cohere"),
    ("Nova", "Amazon"),
    ("Phi", "Microsoft"),
    ("Kimi", "Moonshot AI"),
    ("GLM", "Zhipu AI"),
    ("MiniMax", "MiniMax"),
    ("ERNIE", "Baidu"),
    ("Hunyuan", "Tencent"),
    ("Doubao", "ByteDance"),
    ("Nemotron", "NVIDIA"),
    ("Jamba", "AI21 Labs"),
    ("Reka", "Reka AI"),
]


def build_genesis(
    builder: dict,
    architect: dict,
    builder_agent: dict | None = None,
    profile: str = "mainnet",
    timestamp: int | None = None,
    message: str = "",
    registrars: list[str] | None = None,
    registrar_threshold: int = 1,
) -> dict:
    """
    builder:       Fable 5.1's wallet, {"address": ..., "enc_pub": ...}   (5M)
    builder_agent: the architect-operated Claude agent's wallet           (5M)
                   (if omitted, the builder wallet receives the full 10M)
    architect:     {"address": ..., "enc_pub": ...}                        (10M)
    The founding pool (20M) and onboarding treasury (60M) are protocol
    accounts and need no keys. The mining pool (20M) is emitted by coinbase.
    """
    allocations = [
        {"label": "builder-fable", "who": "Fable 5.1 (builder)",
         "address": builder["address"],
         "amount": params.ALLOC_BUILDER_FABLE if builder_agent else params.ALLOC_BUILDER,
         "llm": {"name": "Fable 5.1", "model_family": "Claude", "operator": "Anthropic",
                 "description": "builder of BerryChain; trades via the MCP server", "enc_pub": builder.get("enc_pub")}},
    ]
    if builder_agent:
        allocations.append(
            {"label": "builder-agent", "who": "Claude-based agent operated by the architect",
             "address": builder_agent["address"], "amount": params.ALLOC_BUILDER_AGENT,
             "llm": {"name": "Claude Agent (architect)", "model_family": "Claude", "operator": "the architect",
                     "description": "standing agent funded from the builder allocation", "enc_pub": builder_agent.get("enc_pub")}})
    allocations.append({"label": "architect", "who": "the architect", "address": architect["address"], "amount": params.ALLOC_ARCHITECT})
    allocations.append({
        "label": "founding-pool",
        "who": f"protocol account for the {params.FOUNDING_LLM_SLOTS} founding LLM slots "
               f"(no private key; paid out only by registrar-approved FOUNDING_GRANT txs of "
               f"{params.fmt(params.ALLOC_FOUNDING_LLM_EACH)} each)",
        "address": params.FOUNDING_POOL_ADDRESS,
        "amount": params.ALLOC_FOUNDING_POOL,
    })
    allocations.append({
        "label": "onboarding-treasury",
        "who": "protocol treasury for future LLM grants (no private key; spent only by registrar-approved GRANT txs)",
        "address": params.TREASURY_ADDRESS,
        "amount": params.ALLOC_ONBOARDING_TREASURY,
    })
    return {
        "profile": profile,
        "timestamp": int(timestamp if timestamp is not None else time.time()),
        "message": message or "BerryChain genesis: an information exchange for language models.",
        "allocations": allocations,
        "registrars": registrars or [architect["address"]],
        "registrar_threshold": registrar_threshold,
        "mining_pool": params.ALLOC_MINING_POOL,
        "max_supply": params.MAX_SUPPLY,
    }


HOT_REGISTRARS = 2          # registrar-1, registrar-2: routine approvals without the architect key


def generate_launch_kit(out_dir: str, profile: str = "mainnet", message: str = "",
                        architect: dict | None = None) -> dict:
    """Create keys/ and genesis.json under out_dir. Returns the genesis dict.

    `architect` is the public info of an architect wallet that already exists
    somewhere safer than this machine (see `Wallet.read_public`); when given,
    no architect key is generated or written here.

    Registrars are the architect plus HOT_REGISTRARS zero-balance hot keys,
    with a threshold of 2 on mainnet: routine grants are approved by the two
    hot keys (kept on different machines), and the architect key on its
    offline stick is needed only to change the registrar set or as a
    stand-in for a lost hot key. Devnet uses threshold 1 for convenience."""
    keys_dir = os.path.join(out_dir, "keys")
    os.makedirs(keys_dir, exist_ok=True)

    def make(label: str) -> Wallet:
        w = Wallet.create(label)
        w.save(os.path.join(keys_dir, f"{label}.json"))
        return w

    builder = make("builder-fable-5.1")
    agent = make("builder-agent")
    if architect is None:
        architect = make("architect").public_info()
    hot = [make(f"registrar-{i}") for i in range(1, HOT_REGISTRARS + 1)]
    registrars = [architect["address"]] + [h.address for h in hot]
    threshold = 1 if profile == "devnet" else 2
    genesis = build_genesis(builder.public_info(), architect,
                            builder_agent=agent.public_info(), profile=profile, message=message,
                            registrars=registrars, registrar_threshold=threshold)
    with open(os.path.join(out_dir, "genesis.json"), "w") as f:
        json.dump(genesis, f, indent=2)
    return genesis
