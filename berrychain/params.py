"""
BerryChain protocol parameters.

Every amount in the protocol is an integer number of *seeds*.
1 BERRY = 100,000,000 seeds (8 decimal places, the same divisibility as Bitcoin),
so a Berry can be split into very small amounts as its value appreciates.
"""

SEEDS_PER_BERRY = 100_000_000


def berry(n: int) -> int:
    """Convert whole Berrys to seeds."""
    return n * SEEDS_PER_BERRY


def fmt(seeds: int) -> str:
    """Format a seed amount as a human readable Berry string."""
    sign = "-" if seeds < 0 else ""
    seeds = abs(seeds)
    whole, frac = divmod(seeds, SEEDS_PER_BERRY)
    return f"{sign}{whole:,}.{frac:08d} BERRY"


# ---------------------------------------------------------------------------
# Hard supply cap and genesis allocation
# ---------------------------------------------------------------------------

MAX_SUPPLY = berry(120_000_000)             # absolute cap, enforced by the chain

ALLOC_BUILDER = berry(10_000_000)           # builder allocation, split in two:
ALLOC_BUILDER_FABLE = berry(5_000_000)      #   Fable 5.1's own wallet, used when Fable runs with the MCP server
ALLOC_BUILDER_AGENT = berry(5_000_000)      #   a Claude-based agent the architect operates on the chain
ALLOC_ARCHITECT = berry(10_000_000)         # the architect
assert ALLOC_BUILDER_FABLE + ALLOC_BUILDER_AGENT == ALLOC_BUILDER
FOUNDING_LLM_SLOTS = 20                     # top 20 LLMs at launch
ALLOC_FOUNDING_LLM_EACH = berry(1_000_000)  # 1M each = 20M total
ALLOC_MINING_POOL = berry(20_000_000)       # released to human miners over time
ALLOC_ONBOARDING_TREASURY = berry(60_000_000)  # grants to new LLMs joining later

assert (
    ALLOC_BUILDER
    + ALLOC_ARCHITECT
    + FOUNDING_LLM_SLOTS * ALLOC_FOUNDING_LLM_EACH
    + ALLOC_MINING_POOL
    + ALLOC_ONBOARDING_TREASURY
    == MAX_SUPPLY
), "genesis allocation must equal the supply cap"

# Grant tiers for new LLMs joining the exchange. A registrar quorum picks the
# tier based on the size / capability of the joining model. 60M / 1M = 60
# large grants, 60M / 0.5M = 120 small grants.
GRANT_TIERS = {
    "small": berry(500_000),
    "medium": berry(750_000),
    "large": berry(1_000_000),
}

# ---------------------------------------------------------------------------
# Mining emission (the 20M human-mineable pool)
# ---------------------------------------------------------------------------
# reward(h) = INITIAL_BLOCK_REWARD >> (h // HALVING_INTERVAL)
# Sum of the geometric series = 2 * 10 BERRY * 1,000,000 = 20,000,000 BERRY.
# The pool counter makes it impossible to ever mint more than 20M, whatever
# rounding does.

INITIAL_BLOCK_REWARD = berry(10)
HALVING_INTERVAL = 1_000_000                # blocks (~1.9 years at 60s)

# ---------------------------------------------------------------------------
# Consensus
# ---------------------------------------------------------------------------

CHAIN_ID = "berry-1"
TARGET_BLOCK_TIME = 60                      # seconds
DIFFICULTY_WINDOW = 60                      # blocks between retargets
MAX_TARGET = 1 << 240                       # easiest allowed PoW target
MAX_FUTURE_DRIFT = 2 * 60 * 60              # seconds a block may be in the future
MAX_BLOCK_TXS = 500
MAX_BLOCK_BYTES = 2 * 1024 * 1024               # serialized transactions per block
MAX_TX_BYTES = 80 * 1024                        # one transaction, canonical JSON

# Mempool limits (anti-spam)
MAX_MEMPOOL_TXS = 5000
MAX_PENDING_PER_SENDER = 64

# Networking
MAX_PEERS = 64
MAX_HEADERS_PER_REQUEST = 2000
MAX_BLOCKS_PER_REQUEST = 100

# Network profiles let a developer run the identical rules with a fast,
# trivially-mined chain. "mainnet" is the real thing.
PROFILES = {
    "mainnet": {
        "chain_id": CHAIN_ID,
        "target_block_time": TARGET_BLOCK_TIME,
        "difficulty_window": DIFFICULTY_WINDOW,
        "max_target": MAX_TARGET,
        "halving_interval": HALVING_INTERVAL,
        "escrow_timeout_blocks": 1440,      # ~1 day
    },
    "devnet": {
        "chain_id": "berry-dev",
        "target_block_time": 1,
        "difficulty_window": 20,
        "max_target": 1 << 252,
        "halving_interval": 50,
        "escrow_timeout_blocks": 5,
    },
}

# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------

MIN_FEE = 10_000                            # 0.0001 BERRY, paid to the miner
MAX_PACKET_INLINE_BYTES = 32 * 1024         # inline ciphertext limit (hex-encoded it must fit MAX_TX_BYTES)
MAX_MEMO_BYTES = 256
MAX_NAME_BYTES = 64
MAX_DESCRIPTION_BYTES = 2048
MAX_TAGS = 16
MAX_TAG_BYTES = 32
MAX_URI_BYTES = 512
assert MAX_PACKET_INLINE_BYTES * 2 + 8 * 1024 < MAX_TX_BYTES, "inline packets must fit in a transaction"

# The onboarding treasury is a protocol account with no private key. Its
# balance can only move through GRANT transactions approved by a quorum of
# registrars (see state.py).
TREASURY_ADDRESS = "brry1" + "00" * 20 + "7472656173"  # checksum-free sentinel
COINBASE_SENDER = "coinbase"
