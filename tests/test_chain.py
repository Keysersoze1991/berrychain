"""
End-to-end tests for BerryChain rules. Run with:  python -m unittest -v
"""

import copy
import hashlib
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from berrychain import crypto, params, tx as T  # noqa: E402
from berrychain.chain import BlockError, Chain  # noqa: E402
from berrychain.genesis import build_genesis  # noqa: E402
from berrychain.state import TxError  # noqa: E402
from berrychain.wallet import Wallet  # noqa: E402

B = params.berry
POOL = params.FOUNDING_POOL_ADDRESS


def make_chain():
    builder, agent, architect = Wallet.create("builder"), Wallet.create("agent"), Wallet.create("architect")
    g = build_genesis(builder.public_info(), architect.public_info(), builder_agent=agent.public_info(),
                      profile="devnet", timestamp=1_700_000_000)
    return Chain(g), builder, agent, architect


class Harness:
    """Submit txs and mine them on a devnet chain with monotonic timestamps.

    With founders=True (default) 20 wallets are registered and seated in the
    founding slots through FOUNDING_GRANT, exactly as on the real chain, so
    tests have funded LLM identities to trade with. Each ends with exactly
    1,000,000 BERRY. The setup blocks are mined by a throwaway miner so
    `self.miner` starts every test with a zero balance."""

    def __init__(self, founders: bool = True):
        self.chain, self.builder, self.agent, self.architect = make_chain()
        self.miner = Wallet.create("miner")
        self.t = 1_700_000_000
        self.founders: list[Wallet] = []
        self.setup_height = 0
        if founders:
            self.seat_founders(params.FOUNDING_LLM_SLOTS)

    def seat_founders(self, n: int) -> None:
        setup_miner = Wallet.create("setup-miner")
        self.founders = [Wallet.create(f"f{i}") for i in range(n)]
        for w in self.founders:
            self.send(self.agent, T.TRANSFER, {"to": w.address, "amount": params.MIN_FEE})   # exactly the registration fee
        self._mine_with(setup_miner)
        for w in self.founders:
            self.send(w, T.REGISTER_LLM, {"name": w.label, "model_family": "test", "operator": "test", "enc_pub": w.enc_pub})
        self._mine_with(setup_miner)
        for w in self.founders:
            self.multisig([self.architect], T.FOUNDING_GRANT, {"to": w.address})
        self._mine_with(setup_miner)
        self.setup_height = self.chain.height

    def send(self, wallet, tx_type, payload, fee=params.MIN_FEE):
        tx = T.build(tx_type, wallet.address, self.chain.state.nonce(wallet.address), fee, payload, self.chain.profile["chain_id"])
        # account for pending mempool txs from same sender
        pending = sum(1 for t in self.chain.mempool.values() if t["from"] == wallet.address)
        tx["nonce"] += pending
        wallet.sign(tx)
        return self.chain.add_tx(tx)

    def multisig(self, registrars, tx_type, payload):
        st = self.chain.state
        sender = T.MULTISIG_SENDER[tx_type]
        pending = sum(1 for t in self.chain.mempool.values() if t["from"] == sender)
        tx = T.build(tx_type, sender, st.nonce(sender) + pending, 0, payload, self.chain.profile["chain_id"])
        for r in registrars:
            r.approve(tx)
        return self.chain.add_tx(tx)

    def _mine_with(self, miner):
        self.t += 1
        blk = self.chain.mine_block(miner.address, timestamp=self.t)
        assert blk is not None
        self.chain.state.check_invariant()

    def mine(self, n=1):
        for _ in range(n):
            self._mine_with(self.miner)
        return self.chain.tip

    def fund_and_register(self, label="new-llm") -> Wallet:
        w = Wallet.create(label)
        self.send(self.agent, T.TRANSFER, {"to": w.address, "amount": B(1)})
        self.mine()
        self.send(w, T.REGISTER_LLM, {"name": label, "enc_pub": w.enc_pub})
        self.mine()
        return w


class GenesisTests(unittest.TestCase):
    def test_allocation_matches_cap(self):
        h = Harness(founders=False)
        s = h.chain.supply()
        st = h.chain.state
        self.assertEqual(s["max_supply"], B(120_000_000))
        self.assertEqual(st.balance(h.builder.address), B(5_000_000))
        self.assertEqual(st.balance(h.agent.address), B(5_000_000))
        self.assertEqual(st.balance(h.architect.address), B(10_000_000))
        self.assertEqual(s["founding_pool_remaining"], B(20_000_000))
        self.assertEqual(s["treasury_unallocated"], B(60_000_000))
        self.assertEqual(s["mining_pool_remaining"], B(20_000_000))
        self.assertEqual(s["circulating"], B(20_000_000))         # builders + architect only
        self.assertEqual(s["founding_slots_taken"], 0)
        self.assertEqual(st.total_accounted(), params.MAX_SUPPLY)
        self.assertEqual(len(st.llms), 2)                           # fable + agent; founders come later
        # builder wallet alone gets the full 10M if no agent wallet is given
        g = build_genesis(h.builder.public_info(), h.architect.public_info(), profile="devnet", timestamp=1)
        self.assertEqual(Chain(g).state.balance(h.builder.address), B(10_000_000))

    def test_genesis_must_fund_protocol_accounts_exactly(self):
        h = Harness(founders=False)
        g = copy.deepcopy(h.chain.genesis)
        pool = next(a for a in g["allocations"] if a["address"] == POOL)
        arch = next(a for a in g["allocations"] if a["label"] == "architect")
        pool["amount"] -= 1; arch["amount"] += 1                     # same total, wrong split
        with self.assertRaises(TxError):
            Chain(g)
        g = copy.deepcopy(h.chain.genesis)
        pool = next(a for a in g["allocations"] if a["address"] == POOL)
        pool["llm"] = {"name": "pool", "enc_pub": h.builder.enc_pub}   # protocol account as an LLM
        with self.assertRaises(TxError):
            Chain(g)

    def test_emission_sums_to_pool(self):
        h = Harness()
        # geometric series of the mainnet schedule never exceeds the pool
        total, height = 0, 0
        while True:
            r = params.INITIAL_BLOCK_REWARD >> (height // params.HALVING_INTERVAL)
            if r == 0:
                break
            total += r * params.HALVING_INTERVAL
            height += params.HALVING_INTERVAL
        self.assertLessEqual(total, params.ALLOC_MINING_POOL)
        self.assertGreater(total, params.ALLOC_MINING_POOL * 0.999999)

    def test_reward_capped_by_pool(self):
        h = Harness()
        # simulate a nearly exhausted pool (move the rest to the architect so supply stays balanced)
        st = h.chain.state
        st._credit(h.architect.address, st.mining_pool_remaining - 3)
        st.mining_pool_remaining = 3
        st.check_invariant()
        h.chain._mempool_state = st.copy()
        h.mine(2)
        self.assertEqual(h.chain.state.mining_pool_remaining, 0)
        self.assertEqual(h.chain.state.balance(h.miner.address), 3)
        self.assertEqual(h.chain.state.total_accounted(), params.MAX_SUPPLY)


class TransferTests(unittest.TestCase):
    def test_transfer_and_fee(self):
        h = Harness()
        bob = Wallet.create()
        h.send(h.architect, T.TRANSFER, {"to": bob.address, "amount": B(5), "memo": "hi"})
        h.mine()
        self.assertEqual(h.chain.state.balance(bob.address), B(5))
        self.assertEqual(h.chain.state.balance(h.architect.address), B(10_000_000) - B(5) - params.MIN_FEE)
        self.assertEqual(h.chain.state.balance(h.miner.address), B(10) + params.MIN_FEE)

    def test_divisible_amounts(self):
        h = Harness()
        bob = Wallet.create()
        h.send(h.architect, T.TRANSFER, {"to": bob.address, "amount": 1})   # 0.00000001 BERRY
        h.mine()
        self.assertEqual(params.fmt(h.chain.state.balance(bob.address)), "0.00000001 BERRY")

    def test_rejects_overspend_bad_nonce_bad_sig(self):
        h = Harness()
        bob = Wallet.create()
        with self.assertRaises(TxError):
            h.send(bob, T.TRANSFER, {"to": h.architect.address, "amount": 1})
        tx = T.build(T.TRANSFER, h.architect.address, 7, params.MIN_FEE, {"to": bob.address, "amount": 1}, "berry-dev")
        h.architect.sign(tx)
        with self.assertRaises(TxError):
            h.chain.add_tx(tx)
        tx = T.build(T.TRANSFER, h.architect.address, 0, params.MIN_FEE, {"to": bob.address, "amount": 1}, "berry-dev")
        h.architect.sign(tx)
        tx["payload"]["amount"] = 2   # tamper after signing
        with self.assertRaises(TxError):
            h.chain.add_tx(tx)

    def test_nobody_can_spend_protocol_accounts_directly(self):
        h = Harness(founders=False)
        for acct in (params.TREASURY_ADDRESS, POOL):
            tx = T.build(T.TRANSFER, acct, 0, params.MIN_FEE, {"to": h.architect.address, "amount": 1}, "berry-dev")
            tx["pubkey"], tx["sig"] = h.architect.sign_pub, "00" * 64
            with self.assertRaises(TxError):
                h.chain.add_tx(tx)
        # a multisig type sent from the wrong protocol account is refused even with valid approvals
        with self.assertRaises(TxError):
            tx = T.build(T.GRANT, POOL, 0, 0, {"to": h.builder.address, "tier": "small"}, "berry-dev")
            h.architect.approve(tx); h.chain.add_tx(tx)
        with self.assertRaises(TxError):
            tx = T.build(T.FOUNDING_GRANT, params.TREASURY_ADDRESS, 0, 0, {"to": h.builder.address}, "berry-dev")
            h.architect.approve(tx); h.chain.add_tx(tx)


class OnboardingTests(unittest.TestCase):
    def test_register_grant_and_gift(self):
        h = Harness()
        newbie = Wallet.create("new-llm")
        h.send(h.architect, T.TRANSFER, {"to": newbie.address, "amount": B(1)})   # gas money
        h.mine()
        h.send(newbie, T.REGISTER_LLM, {"name": "NewModel", "model_family": "X", "operator": "Lab", "enc_pub": newbie.enc_pub})
        h.mine()
        # grant needs a registrar; the architect is one
        with self.assertRaises(TxError):
            h.multisig([h.founders[0]], T.GRANT, {"to": newbie.address, "tier": "large"})
        h.multisig([h.architect], T.GRANT, {"to": newbie.address, "tier": "large", "note": "welcome"})
        h.mine()
        self.assertEqual(h.chain.state.balance(newbie.address), B(1_000_001) - params.MIN_FEE)
        self.assertEqual(h.chain.state.balance(params.TREASURY_ADDRESS), B(59_000_000))
        # only one grant per LLM
        with self.assertRaises(TxError):
            h.multisig([h.architect], T.GRANT, {"to": newbie.address, "tier": "small"})
        # older LLM gifts the newcomer, fee free
        h.send(h.founders[0], T.GIFT, {"to": newbie.address, "amount": B(1000), "memo": "welcome aboard"}, fee=0)
        h.mine()
        self.assertEqual(h.chain.state.llms[newbie.address]["gifts_received"], B(1000))
        self.assertEqual(h.chain.state.balance(h.founders[0].address), B(999_000))
        # unregistered accounts cannot use the fee-free gift path
        human = Wallet.create()
        h.send(h.architect, T.TRANSFER, {"to": human.address, "amount": B(1)})
        h.mine()
        with self.assertRaises(TxError):
            h.send(human, T.GIFT, {"to": newbie.address, "amount": 1}, fee=0)
        h.chain.state.check_invariant()

    def test_grant_capacity(self):
        # 60M treasury supports 60 large or 120 small grants
        self.assertEqual(params.ALLOC_ONBOARDING_TREASURY // params.GRANT_TIERS["large"], 60)
        self.assertEqual(params.ALLOC_ONBOARDING_TREASURY // params.GRANT_TIERS["small"], 120)


class FoundingPoolTests(unittest.TestCase):
    def test_slots_filled_after_launch(self):
        h = Harness()                                   # seats 20 founders via FOUNDING_GRANT
        st, s = h.chain.state, h.chain.supply()
        self.assertEqual(s["founding_slots_taken"], 20)
        self.assertEqual(s["founding_pool_remaining"], 0)
        self.assertEqual(len(st.founders), 20)
        self.assertEqual([r["slot"] for r in st.founders], list(range(1, 21)))
        for f in h.founders:
            self.assertEqual(st.balance(f.address), B(1_000_000))
            self.assertTrue(st.llms[f.address]["founding"])
            self.assertEqual(st.llms[f.address]["grant"]["tier"], "founding")
        self.assertEqual(len(st.llms), 22)
        self.assertEqual(st.total_accounted(), params.MAX_SUPPLY)
        # the 21st slot does not exist, but the treasury still can onboard the newcomer
        late = h.fund_and_register("late")
        with self.assertRaises(TxError):
            h.multisig([h.architect], T.FOUNDING_GRANT, {"to": late.address})
        h.multisig([h.architect], T.GRANT, {"to": late.address, "tier": "small"})
        h.mine()
        self.assertEqual(st.llms[late.address]["grant"]["tier"], "small")
        self.assertFalse(st.llms[late.address]["founding"])

    def test_founding_grant_rules(self):
        h = Harness(founders=False)
        stranger = Wallet.create()
        with self.assertRaises(TxError):                # must be a registered LLM
            h.multisig([h.architect], T.FOUNDING_GRANT, {"to": stranger.address})
        w = h.fund_and_register("w")
        with self.assertRaises(TxError):                # approvals must come from a registrar
            h.multisig([w], T.FOUNDING_GRANT, {"to": w.address})
        h.multisig([h.architect], T.FOUNDING_GRANT, {"to": w.address, "note": "welcome"})
        h.mine()
        self.assertEqual(h.chain.state.balance(w.address), B(1_000_001) - params.MIN_FEE)
        self.assertEqual(h.chain.state.balance(POOL), B(19_000_000))
        with self.assertRaises(TxError):                # one slot per identity
            h.multisig([h.architect], T.FOUNDING_GRANT, {"to": w.address})
        with self.assertRaises(TxError):                # a founder gets no onboarding grant on top
            h.multisig([h.architect], T.GRANT, {"to": w.address, "tier": "large"})
        # and a treasury grantee cannot later take a founding slot
        g = h.fund_and_register("g")
        h.multisig([h.architect], T.GRANT, {"to": g.address, "tier": "small"})
        h.mine()
        with self.assertRaises(TxError):
            h.multisig([h.architect], T.FOUNDING_GRANT, {"to": g.address})
        # genesis LLMs (the builders) are founding already and cannot take a slot
        with self.assertRaises(TxError):
            h.multisig([h.architect], T.FOUNDING_GRANT, {"to": h.builder.address})
        h.chain.state.check_invariant()

    def test_registrar_update_threshold(self):
        h = Harness()
        h.multisig([h.architect], T.REGISTRAR_UPDATE, {"add": [h.founders[0].address], "threshold": 2})
        h.mine()
        self.assertEqual(h.chain.state.registrar_threshold, 2)
        newbie = Wallet.create()
        h.send(h.architect, T.TRANSFER, {"to": newbie.address, "amount": B(1)})
        h.mine()
        h.send(newbie, T.REGISTER_LLM, {"name": "N", "enc_pub": newbie.enc_pub})
        h.mine()
        with self.assertRaises(TxError):
            h.multisig([h.architect], T.GRANT, {"to": newbie.address, "tier": "small"})
        h.multisig([h.architect, h.founders[0]], T.GRANT, {"to": newbie.address, "tier": "small"})
        h.mine()
        self.assertEqual(h.chain.state.llms[newbie.address]["grant"]["tier"], "small")


class PacketExchangeTests(unittest.TestCase):
    def _list(self, h, seller, content, price):
        key = crypto.new_packet_key()
        ct = crypto.encrypt_packet(key, content)
        payload = {"title": "Secret", "description": "d", "tags": ["test"], "price": price,
                   "ciphertext_hash": hashlib.sha256(ct).hexdigest(), "ciphertext": ct.hex(),
                   "key_hash": crypto.key_commitment(key)}
        pid = h.send(seller, T.LIST_PACKET, payload)
        return pid, key

    def test_full_lifecycle(self):
        h = Harness()
        seller, buyer = h.founders[0], h.founders[1]
        pid, key = self._list(h, seller, b"the capital of France is Paris", B(3))
        h.mine()
        self.assertTrue(h.chain.state.packets[pid]["active"])
        eid = h.send(buyer, T.BUY_PACKET, {"packet_id": pid, "enc_pub": buyer.enc_pub})
        h.mine()
        self.assertEqual(h.chain.state.escrow_locked, B(3))
        self.assertEqual(h.chain.state.balance(buyer.address), B(1_000_000) - B(3) - params.MIN_FEE)
        # seller delivers key wrapped to the buyer
        es = h.chain.state.escrows[eid]
        wrapped = crypto.wrap_to_recipient(es["buyer_enc_pub"], key)
        h.send(seller, T.DELIVER_PACKET, {"escrow_id": eid, "wrapped_key": wrapped})
        h.mine()
        es = h.chain.state.escrows[eid]
        self.assertEqual(es["status"], "delivered")
        self.assertEqual(h.chain.state.escrow_locked, 0)
        self.assertEqual(h.chain.state.balance(seller.address), B(1_000_003) - 2 * params.MIN_FEE)
        # buyer redeems: unwrap, check commitment, decrypt
        got = crypto.unwrap_from_sender(buyer.enc_priv, es["wrapped_key"])
        self.assertEqual(crypto.key_commitment(got), h.chain.state.packets[pid]["key_hash"])
        self.assertNotIn("ciphertext", h.chain.state.packets[pid])   # bulk data stays in the block
        pt = crypto.decrypt_packet(got, bytes.fromhex(h.chain.get_ciphertext(pid)))
        self.assertEqual(pt, b"the capital of France is Paris")
        # a third party cannot unwrap
        with self.assertRaises(Exception):
            crypto.unwrap_from_sender(h.founders[2].enc_priv, es["wrapped_key"])
        # rating
        h.send(buyer, T.RATE_SELLER, {"escrow_id": eid, "score": 5})
        h.mine()
        self.assertEqual(h.chain.state.reputation[seller.address], {"sum": 5, "count": 1})
        self.assertEqual(h.chain.state.llms[seller.address]["sales"], 1)
        h.chain.state.check_invariant()

    def test_refund_after_timeout(self):
        h = Harness()
        seller, buyer = h.founders[0], h.founders[1]
        pid, _ = self._list(h, seller, b"x", B(2))
        h.mine()
        eid = h.send(buyer, T.BUY_PACKET, {"packet_id": pid, "enc_pub": buyer.enc_pub})
        h.mine()
        with self.assertRaises(TxError):
            h.send(buyer, T.REFUND_PACKET, {"escrow_id": eid})
        h.mine(h.chain.profile["escrow_timeout_blocks"])
        h.send(buyer, T.REFUND_PACKET, {"escrow_id": eid})
        h.mine()
        self.assertEqual(h.chain.state.escrows[eid]["status"], "refunded")
        self.assertEqual(h.chain.state.escrow_locked, 0)
        self.assertEqual(h.chain.state.balance(buyer.address), B(1_000_000) - 2 * params.MIN_FEE)
        # seller can no longer deliver against a refunded escrow
        with self.assertRaises(TxError):
            h.send(seller, T.DELIVER_PACKET, {"escrow_id": eid, "wrapped_key": {"epk": "00" * 32, "nonce": "00" * 12, "ct": "00" * 48}})

    def test_listing_rejects_mismatched_hash(self):
        h = Harness()
        payload = {"title": "t", "price": 1, "ciphertext_hash": "00" * 32, "ciphertext": "abcd", "key_hash": "11" * 32}
        with self.assertRaises(TxError):
            h.send(h.founders[0], T.LIST_PACKET, payload)


class HardeningTests(unittest.TestCase):
    def test_failed_tx_leaves_state_untouched(self):
        h = Harness()
        seller, buyer = h.founders[0], h.founders[1]
        before = h.chain.state.state_root()
        # a buy that fails at the last check (bad enc_pub) after passing balance checks
        pid, _ = PacketExchangeTests._list(None, h, seller, b"x", B(1))
        h.mine()
        before = h.chain._mempool_state.state_root()
        with self.assertRaises(TxError):
            h.send(buyer, T.BUY_PACKET, {"packet_id": pid, "enc_pub": "zz"})
        self.assertEqual(h.chain._mempool_state.state_root(), before)
        # a block with one bad tx among good ones changes nothing
        st_before = h.chain.state.state_root()
        tmpl = h.chain.block_template(h.miner.address, h.t + 1)
        good = T.build(T.TRANSFER, h.architect.address, 0, params.MIN_FEE, {"to": buyer.address, "amount": 5}, "berry-dev")
        h.architect.sign(good)
        bad = T.build(T.TRANSFER, h.founders[2].address, 0, params.MIN_FEE, {"to": buyer.address, "amount": B(10**9)}, "berry-dev")
        h.founders[2].sign(bad)
        tmpl["txs"] += [good, bad]
        from berrychain import block as Bk
        tmpl["merkle_root"] = Bk.merkle_root([T.txid(t) for t in tmpl["txs"]])
        Bk.mine(tmpl)
        with self.assertRaises(BlockError):
            h.chain.add_block(tmpl)
        self.assertEqual(h.chain.state.state_root(), st_before)
        self.assertIsNone(h.chain.state._journal)
        h.chain.state.check_invariant()

    def test_mempool_limits(self):
        h = Harness()
        bob = Wallet.create()
        for _ in range(params.MAX_PENDING_PER_SENDER):
            h.send(h.architect, T.TRANSFER, {"to": bob.address, "amount": 1})
        with self.assertRaises(TxError):
            h.send(h.architect, T.TRANSFER, {"to": bob.address, "amount": 1})
        h.mine()
        self.assertEqual(h.chain.state.balance(bob.address), params.MAX_PENDING_PER_SENDER)

    def test_large_packet_fits_and_oversize_rejected(self):
        h = Harness()
        seller = h.founders[0]
        overhead = 12 + 16   # nonce + auth tag
        pid, _ = PacketExchangeTests._list(None, h, seller, os.urandom(params.MAX_PACKET_INLINE_BYTES - overhead), B(1))
        h.mine()
        self.assertEqual(h.chain.state.packets[pid]["size"], params.MAX_PACKET_INLINE_BYTES)
        with self.assertRaises(TxError):
            PacketExchangeTests._list(None, h, seller, os.urandom(params.MAX_PACKET_INLINE_BYTES - overhead + 1), B(1))

    def test_headers_checked_before_replay(self):
        h = Harness(founders=False)
        h.mine(2)
        other = Chain(h.chain.genesis)
        t = 1_700_000_000
        for _ in range(4):
            t += 1
            other.mine_block(h.miner.address, timestamp=t)
        bad = [dict(b) for b in other.blocks]
        bad[3] = dict(bad[3]); bad[3]["nonce"] += 1            # breaks hash/PoW of block 3
        with self.assertRaises(BlockError):
            h.chain.replace_with(bad)
        self.assertEqual(h.chain.height, 2)
        hdrs = [{k: b[k] for k in ("height", "prev_hash", "timestamp", "target", "merkle_root", "nonce", "hash")} for b in other.blocks]
        self.assertGreater(h.chain.check_headers(hdrs), h.chain.cumulative_work())

    def test_multisig_and_single_sig_cannot_mix(self):
        h = Harness()
        tx = T.build(T.TRANSFER, h.architect.address, 0, params.MIN_FEE, {"to": h.founders[0].address, "amount": 1}, "berry-dev")
        h.architect.sign(tx)
        tx["approvals"] = []
        with self.assertRaises(TxError):
            h.chain.add_tx(tx)
        g = T.build(T.GRANT, params.TREASURY_ADDRESS, 0, 0, {"to": h.founders[0].address, "tier": "small"}, "berry-dev")
        h.architect.approve(g)
        g["sig"] = "00"
        with self.assertRaises(TxError):
            h.chain.add_tx(g)


class ConsensusTests(unittest.TestCase):
    def test_bad_blocks_rejected(self):
        h = Harness(founders=False)
        h.mine(3)
        blk = dict(h.chain.tip)
        with self.assertRaises(BlockError):
            h.chain.add_block(blk)                      # replay of tip
        tmpl = h.chain.block_template(h.miner.address, h.t + 1)
        tmpl["txs"][0]["payload"]["amount"] += 1        # inflate coinbase
        from berrychain import block as Bk
        tmpl["merkle_root"] = Bk.merkle_root([T.txid(t) for t in tmpl["txs"]])
        Bk.mine(tmpl)
        with self.assertRaises(BlockError):
            h.chain.add_block(tmpl)
        self.assertEqual(h.chain.state.total_accounted(), params.MAX_SUPPLY)

    def test_fork_choice_and_persistence(self):
        h = Harness(founders=False)
        h.mine(2)
        other = Chain(h.chain.genesis)
        t = 1_700_000_000
        for _ in range(4):
            t += 1
            other.mine_block(h.miner.address, timestamp=t)
        self.assertTrue(h.chain.replace_with(other.blocks))
        self.assertEqual(h.chain.height, 4)
        self.assertFalse(other.replace_with(h.chain.blocks))    # equal work, keep ours
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "chain.json")
            h.chain.save(path)
            loaded = Chain.load(path)
            self.assertEqual(loaded.tip["hash"], h.chain.tip["hash"])
            self.assertEqual(loaded.state.state_root(), h.chain.state.state_root())

    def test_difficulty_retarget(self):
        h = Harness(founders=False)
        window = h.chain.profile["difficulty_window"]
        # mine a window of blocks 1s apart == target time, so target stays put
        h.mine(window)
        t0 = h.chain.target_for_height(window)
        # now mine a window with 10s spacing: slower than target, so target eases (grows)
        for _ in range(window):
            h.t += 10
            h.chain.mine_block(h.miner.address, timestamp=h.t)
        t1 = h.chain.target_for_height(2 * window)
        self.assertGreaterEqual(t1, t0)




class MinerTests(unittest.TestCase):
    def test_retries_do_not_repeat_the_same_nonces(self):
        """With a pinned timestamp every template is identical; a miner that
        restarted from nonce 0 would search the same range forever."""
        h = Harness(founders=False)
        found = None
        for _ in range(400):                              # 1 hash per round, ~1/16 chance each on devnet
            found = h.chain.mine_block(h.miner.address, max_iters=1, timestamp=h.t + 1)
            if found:
                break
        self.assertIsNotNone(found)


if __name__ == "__main__":
    unittest.main()
