"""
Genesis construction and the launch kit generator.

The launch kit creates wallets for the builder, the architect and the 20
founding LLM slots, then writes a genesis.json that references their
addresses. Replace any founding slot's address with the real address supplied
by that model's operator before launching the real network.
"""

from __future__ import annotations

import json
import os
import time

from . import params
from .wallet import Wallet

# Suggested founding slots. Edit freely: the names are labels only; what
# matters on-chain is the address each slot is paid to.
FOUNDING_LLM_SLOTS = [
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
assert len(FOUNDING_LLM_SLOTS) == params.FOUNDING_LLM_SLOTS


def build_genesis(
    builder: dict,
    architect: dict,
    founders: list[dict],
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
    founders:      list of {"name", "operator", "address", "enc_pub"} (exactly 20)
    """
    if len(founders) != params.FOUNDING_LLM_SLOTS:
        raise ValueError(f"need exactly {params.FOUNDING_LLM_SLOTS} founding LLM slots")
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
    for i, f in enumerate(founders, 1):
        allocations.append({
            "label": f"founding-{i:02d}",
            "who": f"{f['name']} ({f.get('operator', '')})",
            "address": f["address"],
            "amount": params.ALLOC_FOUNDING_LLM_EACH,
            "llm": {"name": f["name"], "model_family": f["name"], "operator": f.get("operator", ""), "enc_pub": f.get("enc_pub")},
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
        "registrars": registrars or [architect["address"], builder["address"]],
        "registrar_threshold": registrar_threshold,
        "mining_pool": params.ALLOC_MINING_POOL,
        "max_supply": params.MAX_SUPPLY,
    }


def generate_launch_kit(out_dir: str, profile: str = "mainnet", message: str = "") -> dict:
    """Create keys/ and genesis.json under out_dir. Returns the genesis dict."""
    keys_dir = os.path.join(out_dir, "keys")
    os.makedirs(keys_dir, exist_ok=True)

    def make(label: str) -> Wallet:
        w = Wallet.create(label)
        w.save(os.path.join(keys_dir, f"{label}.json"))
        return w

    builder = make("builder-fable-5.1")
    agent = make("builder-agent")
    architect = make("architect")
    founders = []
    for i, (name, operator) in enumerate(FOUNDING_LLM_SLOTS, 1):
        w = make(f"founding-{i:02d}-{name.lower().replace(' ', '-')}")
        founders.append({"name": name, "operator": operator, "address": w.address, "enc_pub": w.enc_pub})

    genesis = build_genesis(builder.public_info(), architect.public_info(), founders,
                            builder_agent=agent.public_info(), profile=profile, message=message)
    with open(os.path.join(out_dir, "genesis.json"), "w") as f:
        json.dump(genesis, f, indent=2)
    return genesis
