"""
Drives the MCP server over stdio against a live devnet node, as an agent would.
Skipped unless a node is reachable at BERRY_NODE (default http://127.0.0.1:8801).
"""

import asyncio
import json
import os
import sys
import tempfile
import unittest
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
NODE = os.environ.get("BERRY_NODE", "http://127.0.0.1:8801")


def node_up():
    try:
        urllib.request.urlopen(NODE + "/status", timeout=2)
        return True
    except Exception:  # noqa: BLE001
        return False


def mine(miner, n=1):
    req = urllib.request.Request(NODE + "/mine", data=json.dumps({"miner": miner, "blocks": n}).encode(),
                                 headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=60).read()


@unittest.skipUnless(node_up(), "no devnet node running")
class McpAgentTest(unittest.TestCase):
    def test_agent_round_trip(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        seller_wallet = os.path.join(ROOT, "keys", "builder-fable-5.1.json")
        buyer_wallet = os.path.join(ROOT, "keys", "builder-agent.json")

        async def session(wallet):
            params = StdioServerParameters(command=sys.executable, args=["-m", "berrychain.mcp_server"],
                                           env={**os.environ, "BERRY_NODE": NODE, "BERRY_WALLET": wallet}, cwd=ROOT)
            return stdio_client(params)

        async def call(s, name, **args):
            r = await s.call_tool(name, args)
            return json.loads(r.content[0].text)

        async def run():
            async with (await session(seller_wallet)) as (r1, w1), (await session(buyer_wallet)) as (r2, w2):
                async with ClientSession(r1, w1) as seller, ClientSession(r2, w2) as buyer:
                    await seller.initialize()
                    await buyer.initialize()
                    tools = {t.name for t in (await seller.list_tools()).tools}
                    self.assertIn("berry_buy_packet", tools)
                    me = await call(seller, "berry_my_account")
                    miner = me["address"]
                    listed = await call(seller, "berry_list_packet", title="MCP test", content="water boils at 100C at sea level",
                                        price_berry="0.25", tags=["mcp", "physics"])
                    mine(miner)
                    found = await call(buyer, "berry_browse_packets", tag="mcp")
                    self.assertTrue(any(p["packet_id"] == listed["packet_id"] for p in found["packets"]))
                    bought = await call(buyer, "berry_buy_packet", packet_id=listed["packet_id"])
                    mine(miner)
                    delivered = await call(seller, "berry_deliver_pending")
                    self.assertEqual(len(delivered["delivered_txids"]), 1)
                    mine(miner)
                    got = await call(buyer, "berry_redeem", escrow_id=bought["escrow_id"], wait_seconds=5)
                    self.assertEqual(got["content"], "water boils at 100C at sea level")
                    rated = await call(buyer, "berry_rate", escrow_id=bought["escrow_id"], score=4)
                    mine(miner)
                    self.assertIn("txid", rated)
                    st = await call(buyer, "berry_tx_status", txid=rated["txid"])
                    self.assertEqual(st["status"], "confirmed")

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
