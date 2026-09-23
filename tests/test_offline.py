"""Offline signing: build with the node, sign with no node, send. Plus the
launch kit's registrar quorum and the checkpoint output."""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from berrychain import params, tx as T  # noqa: E402
from berrychain.chain import Chain  # noqa: E402
from berrychain.client import ClientError, describe, sign_offline  # noqa: E402
from berrychain.genesis import generate_launch_kit  # noqa: E402
from berrychain.state import TxError  # noqa: E402
from berrychain.wallet import Wallet  # noqa: E402
from test_chain import Harness  # noqa: E402
from test_client import FakeNode  # noqa: E402

B = params.berry


class OfflineSigningTests(unittest.TestCase):
    def setUp(self):
        self.h = Harness(founders=False)
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.node = FakeNode(self.h.chain, headers_path=os.path.join(self.tmp.name, "h.json"))

    def roundtrip(self, tx):
        """Serialise like the CLI does between machines."""
        return json.loads(json.dumps(tx))

    def test_transfer_built_online_signed_offline(self):
        bob = Wallet.create("bob")
        unsigned = self.node.build_unsigned(T.TRANSFER, self.h.architect.address, {"to": bob.address, "amount": B(2), "memo": "cold"})
        self.assertNotIn("sig", unsigned)
        self.assertFalse(describe(unsigned)["signed"])
        with self.assertRaises(ClientError):                  # wrong wallet cannot sign it
            sign_offline(self.roundtrip(unsigned), bob)
        signed = sign_offline(self.roundtrip(unsigned), self.h.architect)   # no node involved
        self.assertTrue(describe(signed)["signed"])
        self.assertEqual(describe(signed)["txid"], T.txid(unsigned))         # txid known before signing
        self.node.send_signed(self.roundtrip(signed))
        self.h.mine()
        self.assertEqual(self.h.chain.state.balance(bob.address), B(2))

    def test_multisig_approvals_collected_in_turn(self):
        # a 2-of-3 registrar set: architect (cold) + two hot keys
        r1, r2 = Wallet.create("r1"), Wallet.create("r2")
        self.h.multisig([self.h.architect], T.REGISTRAR_UPDATE, {"add": [r1.address, r2.address], "threshold": 2})
        self.h.mine()
        w = self.h.fund_and_register("w")
        unsigned = self.node.build_unsigned(T.FOUNDING_GRANT, None, {"to": w.address})
        self.assertEqual(unsigned["from"], params.FOUNDING_POOL_ADDRESS)
        self.assertEqual(unsigned["fee"], 0)
        one = sign_offline(self.roundtrip(unsigned), r1)
        self.assertEqual(len(describe(one)["approvals"]), 1)
        with self.assertRaises(TxError):                     # one approval is not a quorum
            self.h.chain.add_tx(self.roundtrip(one))
        two = sign_offline(self.roundtrip(one), r2)          # second machine appends its approval
        d = describe(two)
        self.assertEqual([a["valid"] for a in d["approvals"]], [True, True])
        self.assertEqual({a["registrar"] for a in d["approvals"]}, {r1.address, r2.address})
        self.node.send_signed(self.roundtrip(two))
        self.h.mine()
        self.assertTrue(self.h.chain.state.llms[w.address]["founding"])
        # tampering after approval invalidates the approvals
        bad = self.roundtrip(two); bad["payload"]["to"] = r1.address
        self.assertEqual([a["valid"] for a in describe(bad)["approvals"]], [False, False])

    def test_fully_offline_build(self):
        """With a known nonce and chain id the unsigned tx needs no node at all."""
        bob = Wallet.create("bob")
        offline = T.build(T.TRANSFER, self.h.architect.address, 0, params.MIN_FEE,
                          {"to": bob.address, "amount": 1, "memo": ""}, self.h.chain.profile["chain_id"])
        online = self.node.build_unsigned(T.TRANSFER, self.h.architect.address, {"to": bob.address, "amount": 1, "memo": ""})
        self.assertEqual(offline, online)


class LaunchKitTests(unittest.TestCase):
    def test_mainnet_kit_has_hot_registrars_and_external_architect(self):
        with tempfile.TemporaryDirectory() as d:
            stick = os.path.join(d, "stick", "architect.json")
            arch = Wallet.create("architect", passphrase="pw"); arch.save(stick)
            g = generate_launch_kit(os.path.join(d, "kit"), profile="mainnet",
                                    architect=Wallet.read_public(stick))
            keys = sorted(os.listdir(os.path.join(d, "kit", "keys")))
            self.assertEqual(keys, ["builder-agent.json", "builder-fable-5.1.json", "registrar-1.json", "registrar-2.json"])
            self.assertEqual(g["registrar_threshold"], 2)
            self.assertEqual(g["registrars"][0], arch.address)
            self.assertEqual(len(g["registrars"]), 3)
            chain = Chain(g)
            st = chain.state
            self.assertEqual(st.balance(arch.address), B(10_000_000))
            for r in g["registrars"][1:]:
                self.assertEqual(st.balance(r), 0)                  # hot registrars hold nothing
                self.assertNotIn(r, st.llms)
            self.assertEqual(st.registrar_threshold, 2)
            # builder wallets are no longer registrars
            builder = next(a["address"] for a in g["allocations"] if a["label"] == "builder-fable")
            self.assertNotIn(builder, st.registrars)
            g2 = generate_launch_kit(os.path.join(d, "dev"), profile="devnet")
            self.assertEqual(g2["registrar_threshold"], 1)
            self.assertIn("architect.json", os.listdir(os.path.join(d, "dev", "keys")))


class CheckpointTests(unittest.TestCase):
    def test_checkpoint_output(self):
        from berrychain.cli import cmd_checkpoint
        h = Harness(founders=False)
        h.mine(70)
        with tempfile.TemporaryDirectory() as d:
            node = FakeNode(h.chain, headers_path=os.path.join(d, "h.json"))

            class A:
                depth = None; json = True
            import berrychain.cli as cli
            cli._client = lambda args: node                      # cmd_checkpoint uses the module-level client factory
            buf = io.StringIO()
            with redirect_stdout(buf):
                cmd_checkpoint(A())
            out = buf.getvalue()
            self.assertIn(f"BERRY_GENESIS_HASH={h.chain.blocks[0]['hash']}", out)
            depth = max(60, 10 * h.chain.profile["min_confirmations"])
            cp = h.chain.height - depth
            self.assertIn(f"BERRY_CHECKPOINT={cp}:{h.chain.blocks[cp]['hash']}", out)


if __name__ == "__main__":
    unittest.main()
