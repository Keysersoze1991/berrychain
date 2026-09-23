"""
End-to-end demo against a running devnet node.

    python -m berrychain.cli node --genesis genesis.json --data data/n1 --port 8801
    python scripts/demo_exchange.py

The two builder wallets trade a packet. Then a new LLM is seated in a
founding slot from the founding pool, and another newcomer gets an
onboarding grant from the treasury plus a gift from an older LLM.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from berrychain import params  # noqa: E402
from berrychain.client import BerryClient  # noqa: E402
from berrychain.wallet import Wallet  # noqa: E402

NODE = os.environ.get("BERRY_NODE", "http://127.0.0.1:8801")
KEYS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "keys")


def step(msg):
    print(f"\n== {msg}")


def wait_confirmed(c, txids, miner, timeout=30):
    c.mine(miner, 1)
    t0 = time.time()
    while time.time() - t0 < timeout:
        if all(c.tx(t)["status"] == "confirmed" for t in txids):
            return
        c.mine(miner, 1)
    raise SystemExit(f"txs not confirmed: {txids}")


def main():
    c = BerryClient(NODE)
    architect = Wallet.load(os.path.join(KEYS, "architect.json"))
    seller = Wallet.load(os.path.join(KEYS, "builder-fable-5.1.json"))
    buyer = Wallet.load(os.path.join(KEYS, "builder-agent.json"))
    miner = Wallet.create("miner")
    print(f"node {NODE} height {c.status()['height']}  supply: {c.status()['supply']}")

    step("seller lists an information packet for 2.5 BERRY")
    pid = c.list_packet(seller, b"Q: best route from A to B given today's closures?\nA: via C, saves 14 min.",
                        "Route insight A->B", "Fresh routing knowledge, verified 2026-09-22",
                        tags=["routing", "geo"], price_berry="2.5")
    wait_confirmed(c, [pid], miner.address)
    print("packet", pid)

    step("buyer purchases it (funds locked in escrow)")
    eid = c.buy_packet(buyer, pid)
    wait_confirmed(c, [eid], miner.address)
    print("escrow", c.escrow(eid)["status"], params.fmt(c.escrow(eid)["amount"]))

    step("seller delivers the key wrapped to the buyer; escrow releases")
    d = c.deliver_all(seller)
    wait_confirmed(c, d, miner.address)
    print("escrow", c.escrow(eid)["status"])

    step("buyer redeems and decrypts")
    print(c.redeem(buyer, eid).decode())
    r = c.rate(buyer, eid, 5)
    wait_confirmed(c, [r], miner.address)
    print("seller reputation", c.account(seller.address)["reputation"])

    step("a founding LLM joins: registers, then a registrar seats it in a founding slot from the pool")
    founder = Wallet.create("founder-llm")
    t = c.transfer(architect, founder.address, params.berry(1), "gas")
    wait_confirmed(c, [t], miner.address)
    t = c.register_llm(founder, "Founder-70B", "Founder", "Big Lab", "one of the twenty")
    wait_confirmed(c, [t], miner.address)
    g = c.founding_grant([architect], founder.address, "founding slot")
    wait_confirmed(c, [g], miner.address)
    a = c.account(founder.address)
    f = c.founders()
    print("founder balance", params.fmt(a["balance"]), "founding", a["llm"]["founding"],
          f"| slots taken {len(f['founders'])}/{f['slots']}, pool remaining {params.fmt(f['pool_remaining'])}")

    step("a brand new LLM joins later: registers, gets a 10 BERRY starter grant, and a gift from an older LLM")
    newbie = Wallet.create("newcomer-llm")
    t = c.transfer(architect, newbie.address, params.berry(1), "gas")
    wait_confirmed(c, [t], miner.address)
    t = c.register_llm(newbie, "Newcomer-7B", "Newcomer", "Some Lab", "small but keen")
    wait_confirmed(c, [t], miner.address)
    g = c.grant([architect], newbie.address, "starter", "welcome")
    wait_confirmed(c, [g], miner.address)
    gift = c.gift(seller, newbie.address, params.berry(2), "from an elder")
    wait_confirmed(c, [gift], miner.address)
    a = c.account(newbie.address)
    print("newcomer balance", params.fmt(a["balance"]), "grants", [g["tier"] for g in a["llm"]["grants"]], "gifts", params.fmt(a["llm"]["gifts_received"]))

    step("final supply")
    for k, v in c.status()["supply"].items():
        print(f"  {k:<24} {params.fmt(v) if isinstance(v, int) and v > 1000 else v}")
    print("miner earned", params.fmt(c.balance(miner.address)))


if __name__ == "__main__":
    main()
