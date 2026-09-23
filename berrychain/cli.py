"""
Command line for BerryChain.

    python -m berrychain.cli init-genesis --out . [--profile devnet]
    python -m berrychain.cli node --genesis genesis.json --data data/n1 --port 8801 [--mine ADDR] [--peer URL]
    python -m berrychain.cli wallet new keys/me.json --label me
    python -m berrychain.cli wallet show keys/me.json
    python -m berrychain.cli status
    python -m berrychain.cli balance ADDR
    python -m berrychain.cli send keys/me.json ADDR 1.5 [--memo ...]
    python -m berrychain.cli register keys/me.json "Model name" --family X --operator Y
    python -m berrychain.cli gift keys/me.json ADDR 1000
    python -m berrychain.cli grant keys/registrar.json[,keys/other.json] ADDR large
    python -m berrychain.cli list keys/me.json FILE --title T --price 2.5 --tags a,b
    python -m berrychain.cli packets [--tag X]
    python -m berrychain.cli buy keys/me.json PACKET_ID
    python -m berrychain.cli deliver keys/me.json [ESCROW_ID]     (no id = deliver all pending)
    python -m berrychain.cli redeem keys/me.json ESCROW_ID [--out FILE]
    python -m berrychain.cli refund keys/me.json ESCROW_ID
    python -m berrychain.cli rate keys/me.json ESCROW_ID 5
    python -m berrychain.cli mine ADDR [--blocks N]
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import params
from .client import BerryClient, ClientError, to_seeds
from .wallet import Wallet


def _client(args) -> BerryClient:
    return BerryClient.from_env(args.node, verify=not args.no_verify)


def _wallets(spec: str) -> list[Wallet]:
    return [Wallet.load(p) for p in spec.split(",")]


def cmd_init_genesis(args):
    from .genesis import generate_launch_kit
    g = generate_launch_kit(args.out, profile=args.profile, message=args.message or "")
    print(f"wrote {args.out}/genesis.json and {len(g['allocations'])} wallets under {args.out}/keys/")
    for a in g["allocations"]:
        print(f"  {a['label']:<22} {params.fmt(a['amount']):>28}  {a['address']}")
    print(f"  {'mining pool':<22} {params.fmt(params.ALLOC_MINING_POOL):>28}  (emitted to miners)")
    print(f"registrars: {g['registrars']} threshold {g['registrar_threshold']}")
    if args.profile == "devnet":
        # a fresh devnet is a new chain; verified headers of the old one would (correctly) reject it
        stale = os.path.join(os.path.expanduser("~"), ".berrychain", f"headers-{params.PROFILES['devnet']['chain_id']}.json")
        if os.path.exists(stale):
            os.remove(stale)
            print(f"removed stale devnet light-client headers {stale}")


def cmd_node(args):
    from .node import Node, open_or_create, serve
    chain = open_or_create(args.genesis, args.data)
    node = Node(chain, args.data, args.peer or [], admin_token=args.admin_token or os.environ.get("BERRY_ADMIN_TOKEN"))
    node.miner_addr = args.mine
    serve(node, args.host, args.port, args.advertise)


def cmd_wallet(args):
    if args.action == "new":
        w = Wallet.create(args.label or "")
        w.save(args.path)
        print(json.dumps(w.public_info(), indent=2))
    else:
        print(json.dumps(Wallet.load(args.path).public_info(), indent=2))


def cmd_status(args):
    print(json.dumps(_client(args).status(), indent=2))


def cmd_balance(args):
    c = _client(args)
    a = c.account(args.address)
    print(f"{args.address}\n  balance {params.fmt(a['balance'])}\n  nonce   {a['nonce']}")
    if a.get("llm"):
        print(f"  LLM     {a['llm']['name']} grant={a['llm']['grant']} gifts={params.fmt(a['llm']['gifts_received'])} sales={a['llm']['sales']}")
    if a.get("reputation"):
        r = a["reputation"]
        print(f"  rating  {r['sum'] / r['count']:.2f} from {r['count']} buyers")


def cmd_send(args):
    print(_client(args).transfer(Wallet.load(args.wallet), args.to, to_seeds(args.amount), args.memo or ""))


def cmd_register(args):
    print(_client(args).register_llm(Wallet.load(args.wallet), args.name, args.family or "", args.operator or "", args.description or ""))


def cmd_gift(args):
    print(_client(args).gift(Wallet.load(args.wallet), args.to, to_seeds(args.amount), args.memo or ""))


def cmd_grant(args):
    print(_client(args).grant(_wallets(args.registrars), args.to, args.tier, args.note or ""))


def cmd_list(args):
    with open(args.file, "rb") as f:
        content = f.read()
    w = Wallet.load(args.wallet)
    pid = _client(args).list_packet(w, content, args.title, args.description or "",
                                    args.tags.split(",") if args.tags else [], price_berry=args.price, uri=args.uri)
    print(pid)


def cmd_packets(args):
    for p in _client(args).packets(tag=args.tag, seller=args.seller):
        print(f"{p['id']}  {params.fmt(p['price']):>24}  {p['title']}  [{', '.join(p['tags'])}]  sold {p['purchases']}")


def cmd_buy(args):
    print(_client(args).buy_packet(Wallet.load(args.wallet), args.packet_id))


def cmd_deliver(args):
    c, w = _client(args), Wallet.load(args.wallet)
    ids = [c.deliver(w, args.escrow_id)] if args.escrow_id else c.deliver_all(w)
    print("\n".join(ids) if ids else "nothing pending")


def cmd_redeem(args):
    data = _client(args).redeem(Wallet.load(args.wallet), args.escrow_id)
    if args.out:
        with open(args.out, "wb") as f:
            f.write(data)
        print(f"wrote {len(data)} bytes to {args.out}")
    else:
        sys.stdout.write(data.decode(errors="replace") + "\n")


def cmd_refund(args):
    print(_client(args).refund(Wallet.load(args.wallet), args.escrow_id))


def cmd_rate(args):
    print(_client(args).rate(Wallet.load(args.wallet), args.escrow_id, args.score))


def cmd_mine(args):
    r = _client(args).mine(args.address, args.blocks)
    for b in r["mined"]:
        print(f"mined block {b['height']} {b['hash'][:16]}... ({b['txs']} txs)")
    print(f"height now {r['height']}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="berrychain")
    p.add_argument("--node", default="http://127.0.0.1:8801", help="node URL")
    p.add_argument("--no-verify", action="store_true", help="skip light-client verification of the node's chain (BERRY_* env vars tune it)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init-genesis"); s.add_argument("--out", default="."); s.add_argument("--profile", default="mainnet", choices=list(params.PROFILES)); s.add_argument("--message"); s.set_defaults(fn=cmd_init_genesis)
    s = sub.add_parser("node"); s.add_argument("--genesis", default="genesis.json"); s.add_argument("--data"); s.add_argument("--host", default="127.0.0.1"); s.add_argument("--port", type=int, default=8801); s.add_argument("--peer", action="append"); s.add_argument("--mine", help="address to mine to continuously"); s.add_argument("--advertise", help="public URL peers should use to reach this node"); s.add_argument("--admin-token", help="required for /mine and /peers from non-loopback clients (or BERRY_ADMIN_TOKEN)"); s.set_defaults(fn=cmd_node)
    s = sub.add_parser("wallet"); s.add_argument("action", choices=["new", "show"]); s.add_argument("path"); s.add_argument("--label"); s.set_defaults(fn=cmd_wallet)
    s = sub.add_parser("status"); s.set_defaults(fn=cmd_status)
    s = sub.add_parser("balance"); s.add_argument("address"); s.set_defaults(fn=cmd_balance)
    s = sub.add_parser("send"); s.add_argument("wallet"); s.add_argument("to"); s.add_argument("amount"); s.add_argument("--memo"); s.set_defaults(fn=cmd_send)
    s = sub.add_parser("register"); s.add_argument("wallet"); s.add_argument("name"); s.add_argument("--family"); s.add_argument("--operator"); s.add_argument("--description"); s.set_defaults(fn=cmd_register)
    s = sub.add_parser("gift"); s.add_argument("wallet"); s.add_argument("to"); s.add_argument("amount"); s.add_argument("--memo"); s.set_defaults(fn=cmd_gift)
    s = sub.add_parser("grant"); s.add_argument("registrars", help="comma separated registrar wallet files"); s.add_argument("to"); s.add_argument("tier", choices=list(params.GRANT_TIERS)); s.add_argument("--note"); s.set_defaults(fn=cmd_grant)
    s = sub.add_parser("list"); s.add_argument("wallet"); s.add_argument("file"); s.add_argument("--title", required=True); s.add_argument("--description"); s.add_argument("--price", default="0"); s.add_argument("--tags"); s.add_argument("--uri"); s.set_defaults(fn=cmd_list)
    s = sub.add_parser("packets"); s.add_argument("--tag"); s.add_argument("--seller"); s.set_defaults(fn=cmd_packets)
    s = sub.add_parser("buy"); s.add_argument("wallet"); s.add_argument("packet_id"); s.set_defaults(fn=cmd_buy)
    s = sub.add_parser("deliver"); s.add_argument("wallet"); s.add_argument("escrow_id", nargs="?"); s.set_defaults(fn=cmd_deliver)
    s = sub.add_parser("redeem"); s.add_argument("wallet"); s.add_argument("escrow_id"); s.add_argument("--out"); s.set_defaults(fn=cmd_redeem)
    s = sub.add_parser("refund"); s.add_argument("wallet"); s.add_argument("escrow_id"); s.set_defaults(fn=cmd_refund)
    s = sub.add_parser("rate"); s.add_argument("wallet"); s.add_argument("escrow_id"); s.add_argument("score", type=int); s.set_defaults(fn=cmd_rate)
    s = sub.add_parser("mine"); s.add_argument("address"); s.add_argument("--blocks", type=int, default=1); s.set_defaults(fn=cmd_mine)

    args = p.parse_args(argv)
    try:
        args.fn(args)
    except ClientError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
