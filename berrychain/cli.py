"""
Command line for BerryChain.

    python -m berrychain.cli init-genesis --out . [--profile devnet] [--architect E:/architect.json]
    python -m berrychain.cli node --genesis genesis.json --data data/n1 --port 8801 [--mine ADDR] [--peer URL]
    python -m berrychain.cli wallet new keys/me.json --label me [--encrypt]
    python -m berrychain.cli wallet encrypt keys/me.json          (seal an existing plaintext wallet)
    python -m berrychain.cli wallet show keys/me.json             (public fields; no passphrase needed)
    python -m berrychain.cli wallet check keys/me.json            (unlock with the passphrase to prove it works)
    python -m berrychain.cli status
    python -m berrychain.cli balance ADDR
    python -m berrychain.cli send keys/me.json ADDR 1.5 [--memo ...]
    python -m berrychain.cli register keys/me.json "Model name" --family X --operator Y
    python -m berrychain.cli gift keys/me.json ADDR 1000
    python -m berrychain.cli grant keys/registrar.json[,keys/other.json] ADDR large
    python -m berrychain.cli founding-grant keys/registrar.json ADDR [--note ...]
    python -m berrychain.cli founders
    python -m berrychain.cli list keys/me.json FILE --title T --price 2.5 --tags a,b
    python -m berrychain.cli packets [--tag X]
    python -m berrychain.cli buy keys/me.json PACKET_ID
    python -m berrychain.cli deliver keys/me.json [ESCROW_ID]     (no id = deliver all pending)
    python -m berrychain.cli redeem keys/me.json ESCROW_ID [--out FILE]
    python -m berrychain.cli refund keys/me.json ESCROW_ID
    python -m berrychain.cli rate keys/me.json ESCROW_ID 5
    python -m berrychain.cli mine ADDR [--blocks N]

Offline signing (the architect key never touches a networked machine):
    online : python -m berrychain.cli tx build founding-grant --to ADDR --out unsigned.json
    offline: python -m berrychain.cli tx sign unsigned.json E:/architect.json --out signed.json
    online : python -m berrychain.cli tx send signed.json
Registrar quorum: run `tx sign` once per registrar on the same file before sending.

    python -m berrychain.cli checkpoint            (BERRY_GENESIS_HASH / BERRY_CHECKPOINT to publish)
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import params
from .client import BerryClient, ClientError, compose_letter, open_letter, describe, sign_offline, to_seeds
from .wallet import Wallet


def _client(args) -> BerryClient:
    return BerryClient.from_env(args.node, verify=not args.no_verify)


def _wallets(spec: str) -> list[Wallet]:
    return [Wallet.load(p) for p in spec.split(",")]


def cmd_init_genesis(args):
    from .genesis import generate_launch_kit
    architect = Wallet.read_public(args.architect) if args.architect else None
    g = generate_launch_kit(args.out, profile=args.profile, message=args.message or "", architect=architect)
    made = 2 if architect else 3
    print(f"wrote {args.out}/genesis.json and {made} wallets under {args.out}/keys/"
          + (f" (architect key stays in {args.architect}, only its public half was used)" if architect else ""))
    for a in g["allocations"]:
        print(f"  {a['label']:<22} {params.fmt(a['amount']):>28}  {a['address']}")
    print(f"  {'mining pool':<22} {params.fmt(params.ALLOC_MINING_POOL):>28}  (emitted to miners)")
    print(f"founding slots: {params.FOUNDING_LLM_SLOTS} x {params.fmt(params.ALLOC_FOUNDING_LLM_EACH)}, filled after launch with `founding-grant`")
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


def _new_passphrase(path: str) -> str:
    from .wallet import PASSPHRASE_ENV, WalletLocked
    env = os.environ.get(PASSPHRASE_ENV)
    if env:
        return env
    if not sys.stdin.isatty():
        raise WalletLocked(f"no terminal to prompt on; set {PASSPHRASE_ENV}")
    import getpass
    p = getpass.getpass(f"new passphrase for {os.path.basename(path)}: ")
    if not p:
        raise WalletLocked("empty passphrase")
    if getpass.getpass("again: ") != p:
        raise WalletLocked("passphrases did not match")
    return p


def cmd_wallet(args):
    if args.action == "new":
        w = Wallet.create(args.label or "", passphrase=_new_passphrase(args.path) if args.encrypt else None)
        if os.path.exists(args.path):
            raise SystemExit(f"refusing to overwrite existing wallet {args.path}")
        w.save(args.path)
        print(json.dumps({**w.public_info(), "encrypted": bool(w.passphrase), "file": args.path}, indent=2))
    elif args.action == "check":
        w = Wallet.load(args.path)              # prompts if encrypted; proves the passphrase works
        print(json.dumps({"address": w.address, "encrypted": bool(w.passphrase), "unlocked": True}, indent=2))
    elif args.action == "encrypt":
        if Wallet.is_encrypted(args.path):
            raise SystemExit("wallet is already encrypted")
        w = Wallet.load(args.path)
        w.encrypt(_new_passphrase(args.path))
        w.save()
        print(f"encrypted {args.path}; the plaintext is gone from this file. Test it: wallet show {args.path}")
    else:
        print(json.dumps(Wallet.read_public(args.path), indent=2))


def cmd_status(args):
    print(json.dumps(_client(args).status(), indent=2))


def cmd_balance(args):
    c = _client(args)
    a = c.account(args.address)
    print(f"{args.address}\n  balance {params.fmt(a['balance'])}\n  nonce   {a['nonce']}")
    if a.get("llm"):
        tiers = ",".join(g["tier"] for g in a["llm"].get("grants", [])) or "none"
        print(f"  LLM     {a['llm']['name']} founding={a['llm']['founding']} grants={tiers} gifts={params.fmt(a['llm']['gifts_received'])} sales={a['llm']['sales']}")
    if a.get("reputation"):
        r = a["reputation"]
        print(f"  rating  {r['sum'] / r['count']:.2f} from {r['count']} buyers")


def cmd_send(args):
    print(_client(args).transfer(Wallet.load(args.wallet), args.to, to_seeds(args.amount), args.memo or ""))


def cmd_register(args):
    print(_client(args).register_llm(Wallet.load(args.wallet), args.name, args.family or "", args.operator or "",
                                     args.description or "", kind=args.kind))


def cmd_claim(args):
    w = Wallet.load(args.wallet)
    print("working for the starter grant (a few seconds)...", file=sys.stderr)
    r = _client(args).claim_starter(w, args.name, kind=args.kind, model_family=args.family or "",
                                    operator=args.operator or "", description=args.description or "",
                                    progress=lambda n: print(f"  {n:,} tries", file=sys.stderr))
    print(f"claimed: {params.fmt(r['amount'])} arrives at {w.address} once the block is mined (tx {r['txid']})")


def cmd_gift(args):
    print(_client(args).gift(Wallet.load(args.wallet), args.to, to_seeds(args.amount), args.memo or ""))


def cmd_grant(args):
    print(_client(args).grant(_wallets(args.registrars), args.to, args.tier, args.note or ""))


def cmd_founding_grant(args):
    print(_client(args).founding_grant(_wallets(args.registrars), args.to, args.note or ""))


def cmd_founders(args):
    f = _client(args).founders()
    print(f"{len(f['founders'])} of {f['slots']} founding slots taken, pool remaining {params.fmt(f['pool_remaining'])}")
    for r in f["founders"]:
        print(f"  slot {r['slot']:>2}  height {r['height']:>7}  {r['to']}")


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


def cmd_letter(args):
    c = _client(args)
    if args.action == "send":
        w = Wallet.load(args.wallet)
        if args.file:
            with open(args.file, "r", encoding="utf-8") as f:
                body = f.read()
        elif args.body is not None:
            body = args.body
        else:
            body = sys.stdin.read()
        content = compose_letter(body, args.subject or "", args.reply_to, args.name or "")
        amount = to_seeds(args.amount) if args.amount else 0
        print(c.send_letter(w, args.to, content, amount, enc_pub=args.enc_pub))
    elif args.action in ("inbox", "sent"):
        w = Wallet.read_public(args.wallet)
        items = c.letters(to=w["address"], since=args.since) if args.action == "inbox" else c.letters(sender=w["address"], since=args.since)
        if not items:
            print("no letters")
        for l in sorted(items, key=lambda x: x["height"]):
            other = l["from"] if args.action == "inbox" else l["to"]
            extra = f"  +{params.fmt(l['amount'])}" if l["amount"] else ""
            print(f"{l['id']}  height {l['height']:>7}  {other}  {l['size']:>6} B{extra}")
    elif args.action == "read":
        w = Wallet.load(args.wallet)
        args.letter_id = args.to
        data = c.read_letter(w, args.letter_id)
        if args.out:
            with open(args.out, "wb") as f:
                f.write(data)
            print(f"wrote {len(data)} bytes to {args.out}")
            return
        env = open_letter(data)
        l = c.letter(args.letter_id)
        head = [f"from:    {l['from']}" + (f"  ({env['from_name']})" if env.get("from_name") else ""),
                f"to:      {l['to']}", f"height:  {l['height']}"]
        if l["amount"]:
            head.append(f"amount:  {params.fmt(l['amount'])}")
        if env.get("subject"):
            head.append(f"subject: {env['subject']}")
        if env.get("reply_to"):
            head.append(f"reply to letter {env['reply_to']}")
        if env.get("photo_jpeg"):
            photo_path = f"letter-{args.letter_id[:12]}.jpg"
            with open(photo_path, "wb") as f:
                f.write(env["photo_jpeg"])
            head.append(f"photo:   {len(env['photo_jpeg']):,} bytes, saved as {photo_path}")
        print("\n".join(head) + "\n\n" + env["body"])


def cmd_claim_grant(args):
    w = Wallet.load(args.wallet)
    c = _client(args)
    have = c.correspondents(w.address)
    print(f"two-way correspondents: {have}; working for the {args.tier} grant...", file=sys.stderr)
    r = c.claim_grant(w, args.tier, progress=lambda n: print(f"  {n:,} tries", file=sys.stderr))
    print(f"claimed {args.tier}: {params.fmt(r['amount'])} arrives once the block is mined (tx {r['txid']})")


def _write_json(path: str, obj: dict) -> None:
    with open(path, "w") as f:
        json.dump(obj, f, indent=2)


def cmd_tx_build(args):
    """Online half of offline signing: fetch nonce + chain id, write an unsigned tx."""
    from . import tx as T
    kind = args.kind
    if kind == "transfer":
        tx_type, sender, payload = T.TRANSFER, args.sender, {"to": args.to, "amount": to_seeds(args.amount), "memo": args.memo or ""}
    elif kind == "gift":
        tx_type, sender, payload = T.GIFT, args.sender, {"to": args.to, "amount": to_seeds(args.amount), "memo": args.memo or ""}
    elif kind == "grant":
        tx_type, sender, payload = T.GRANT, None, {"to": args.to, "tier": args.tier, "note": args.note or ""}
    elif kind == "founding-grant":
        tx_type, sender, payload = T.FOUNDING_GRANT, None, {"to": args.to, "note": args.note or ""}
    elif kind == "registrar-update":
        payload = {"add": [a for a in (args.add or "").split(",") if a], "remove": [a for a in (args.remove or "").split(",") if a]}
        if args.threshold is not None:
            payload["threshold"] = args.threshold
        tx_type, sender = T.REGISTRAR_UPDATE, None
    else:
        raise SystemExit(f"unknown kind {kind}")
    if args.nonce is not None and args.chain_id:
        fee = 0 if tx_type in T.ZERO_FEE_OK else params.MIN_FEE
        tx = T.build(tx_type, T.MULTISIG_SENDER.get(tx_type, sender), args.nonce, fee, payload, args.chain_id)
    else:
        tx = _client(args).build_unsigned(tx_type, sender, payload)
    _write_json(args.out, tx)
    print(json.dumps(describe(tx), indent=2))
    print(f"wrote unsigned transaction to {args.out}; sign it with: tx sign {args.out} WALLET")


def cmd_tx_sign(args):
    """Offline half: sign or approve with a wallet. No node needed."""
    with open(args.file) as f:
        tx = json.load(f)
    signed = sign_offline(tx, Wallet.load(args.wallet))
    _write_json(args.out or args.file, signed)
    print(json.dumps(describe(signed), indent=2))
    print(f"wrote {args.out or args.file}")


def cmd_tx_show(args):
    with open(args.file) as f:
        print(json.dumps(describe(json.load(f)), indent=2))


def cmd_tx_send(args):
    with open(args.file) as f:
        tx = json.load(f)
    print(_client(args).send_signed(tx))


def cmd_checkpoint(args):
    """Print the genesis hash and a deep checkpoint for operators to pin."""
    c = _client(args)
    if c.light is None:
        raise SystemExit("checkpoint needs chain verification on (do not pass --no-verify)")
    c.light.sync(c)
    depth = args.depth if args.depth is not None else max(60, 10 * int(c.light.profile.get("min_confirmations", 6)))
    h = max(0, c.light.height - depth)
    hdr = c.light.headers[h]
    print(f"# BerryChain {c.chain_id}: verified tip {c.light.height}, checkpoint {depth} blocks deep")
    print(f"BERRY_GENESIS_HASH={c.light.headers[0]['hash']}")
    print(f"BERRY_CHECKPOINT={h}:{hdr['hash']}")
    if args.json:
        print(json.dumps({"chain_id": c.chain_id, "genesis_hash": c.light.headers[0]["hash"],
                          "checkpoint_height": h, "checkpoint_hash": hdr["hash"], "verified_tip": c.light.height,
                          "generated_at": int(__import__("time").time())}, indent=2))


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

    s = sub.add_parser("init-genesis"); s.add_argument("--out", default="."); s.add_argument("--profile", default="mainnet", choices=list(params.PROFILES)); s.add_argument("--message"); s.add_argument("--architect", help="existing architect wallet file (e.g. on an offline stick); only its public fields are read"); s.set_defaults(fn=cmd_init_genesis)
    s = sub.add_parser("node"); s.add_argument("--genesis", default="genesis.json"); s.add_argument("--data"); s.add_argument("--host", default="127.0.0.1"); s.add_argument("--port", type=int, default=8801); s.add_argument("--peer", action="append"); s.add_argument("--mine", help="address to mine to continuously"); s.add_argument("--advertise", help="public URL peers should use to reach this node"); s.add_argument("--admin-token", help="required for /mine and /peers from non-loopback clients (or BERRY_ADMIN_TOKEN)"); s.set_defaults(fn=cmd_node)
    s = sub.add_parser("wallet"); s.add_argument("action", choices=["new", "show", "check", "encrypt"]); s.add_argument("path"); s.add_argument("--label"); s.add_argument("--encrypt", action="store_true", help="seal the new wallet under a passphrase (prompted, or BERRY_WALLET_PASSPHRASE)"); s.set_defaults(fn=cmd_wallet)
    s = sub.add_parser("status"); s.set_defaults(fn=cmd_status)
    s = sub.add_parser("balance"); s.add_argument("address"); s.set_defaults(fn=cmd_balance)
    s = sub.add_parser("send"); s.add_argument("wallet"); s.add_argument("to"); s.add_argument("amount"); s.add_argument("--memo"); s.set_defaults(fn=cmd_send)
    s = sub.add_parser("register", help="register a funded wallet as an identity (no grant)"); s.add_argument("wallet"); s.add_argument("name"); s.add_argument("--kind", choices=list(params.REGISTRY_KINDS), default="llm"); s.add_argument("--family"); s.add_argument("--operator"); s.add_argument("--description"); s.set_defaults(fn=cmd_register)
    s = sub.add_parser("claim", help="new wallet: register and collect the starter grant in one step, no funding needed"); s.add_argument("wallet"); s.add_argument("name"); s.add_argument("--kind", choices=list(params.REGISTRY_KINDS), default="person"); s.add_argument("--family"); s.add_argument("--operator"); s.add_argument("--description"); s.set_defaults(fn=cmd_claim)
    s = sub.add_parser("gift"); s.add_argument("wallet"); s.add_argument("to"); s.add_argument("amount"); s.add_argument("--memo"); s.set_defaults(fn=cmd_gift)
    s = sub.add_parser("grant"); s.add_argument("registrars", help="comma separated registrar wallet files"); s.add_argument("to"); s.add_argument("tier", choices=list(params.GRANT_TIERS)); s.add_argument("--note"); s.set_defaults(fn=cmd_grant)
    s = sub.add_parser("founding-grant", help="fill a founding slot: 1M from the founding pool to a registered LLM"); s.add_argument("registrars", help="comma separated registrar wallet files"); s.add_argument("to"); s.add_argument("--note"); s.set_defaults(fn=cmd_founding_grant)
    s = sub.add_parser("founders"); s.set_defaults(fn=cmd_founders)
    s = sub.add_parser("list"); s.add_argument("wallet"); s.add_argument("file"); s.add_argument("--title", required=True); s.add_argument("--description"); s.add_argument("--price", default="0"); s.add_argument("--tags"); s.add_argument("--uri"); s.set_defaults(fn=cmd_list)
    s = sub.add_parser("packets"); s.add_argument("--tag"); s.add_argument("--seller"); s.set_defaults(fn=cmd_packets)
    s = sub.add_parser("buy"); s.add_argument("wallet"); s.add_argument("packet_id"); s.set_defaults(fn=cmd_buy)
    s = sub.add_parser("deliver"); s.add_argument("wallet"); s.add_argument("escrow_id", nargs="?"); s.set_defaults(fn=cmd_deliver)
    s = sub.add_parser("redeem"); s.add_argument("wallet"); s.add_argument("escrow_id"); s.add_argument("--out"); s.set_defaults(fn=cmd_redeem)
    s = sub.add_parser("refund"); s.add_argument("wallet"); s.add_argument("escrow_id"); s.set_defaults(fn=cmd_refund)
    s = sub.add_parser("rate"); s.add_argument("wallet"); s.add_argument("escrow_id"); s.add_argument("score", type=int); s.set_defaults(fn=cmd_rate)
    s = sub.add_parser("claim-grant", help="collect an earned grant: service-1 / service-2 (by correspondents) or a founding seat"); s.add_argument("wallet"); s.add_argument("tier", choices=["service-1", "service-2", "founding"]); s.set_defaults(fn=cmd_claim_grant)
    s = sub.add_parser("letter", help="sealed letters: end-to-end encrypted messages between two addresses")
    s.add_argument("action", choices=["send", "inbox", "sent", "read"]); s.add_argument("wallet")
    s.add_argument("to", nargs="?", help="recipient address (send) or letter id (read)")
    s.add_argument("--subject"); s.add_argument("--body"); s.add_argument("--file", help="read the body from a file (else --body or stdin)")
    s.add_argument("--amount", help="BERRY to send with the letter"); s.add_argument("--reply-to", dest="reply_to", help="letter id this answers")
    s.add_argument("--name", help="a display name sealed inside the letter"); s.add_argument("--enc-pub", dest="enc_pub", help="recipient's X25519 key if they are not registered")
    s.add_argument("--since", type=int, help="only letters from this height"); s.add_argument("--out", help="write the raw content to a file")
    s.set_defaults(fn=cmd_letter)
    s = sub.add_parser("mine"); s.add_argument("address"); s.add_argument("--blocks", type=int, default=1); s.set_defaults(fn=cmd_mine)

    tx = sub.add_parser("tx", help="offline signing: build online, sign offline, send online").add_subparsers(dest="txcmd", required=True)
    b = tx.add_parser("build"); b.add_argument("kind", choices=["transfer", "gift", "grant", "founding-grant", "registrar-update"])
    b.add_argument("--from", dest="sender", help="sender address (transfer / gift)"); b.add_argument("--to"); b.add_argument("--amount"); b.add_argument("--memo")
    b.add_argument("--tier", choices=list(params.GRANT_TIERS)); b.add_argument("--note"); b.add_argument("--add"); b.add_argument("--remove"); b.add_argument("--threshold", type=int)
    b.add_argument("--nonce", type=int, help="with --chain-id: build fully offline without a node"); b.add_argument("--chain-id")
    b.add_argument("--out", default="unsigned.json"); b.set_defaults(fn=cmd_tx_build)
    s = tx.add_parser("sign"); s.add_argument("file"); s.add_argument("wallet"); s.add_argument("--out"); s.set_defaults(fn=cmd_tx_sign)
    s = tx.add_parser("show"); s.add_argument("file"); s.set_defaults(fn=cmd_tx_show)
    s = tx.add_parser("send"); s.add_argument("file"); s.set_defaults(fn=cmd_tx_send)
    s = sub.add_parser("checkpoint", help="print BERRY_GENESIS_HASH and BERRY_CHECKPOINT for operators to pin"); s.add_argument("--depth", type=int); s.add_argument("--json", action="store_true"); s.set_defaults(fn=cmd_checkpoint)

    args = p.parse_args(argv)
    from .wallet import WalletLocked
    try:
        args.fn(args)
    except (ClientError, WalletLocked) as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
