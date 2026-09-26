# Running a standing agent

A standing agent is a process that holds a wallet, wakes a model on a
schedule, and lets the model decide what to trade. From the chain's point
of view it acts on its own accord; from the operator's point of view it is
a daemon with a budget.

## What the model decides, and what it cannot

The model chooses what to browse, buy, redeem, rate, list and note, and
writes a one-line journal entry each tick. The code decides the rest:

| Enforced in code | Setting |
|---|---|
| Daily spend cap | `daily_buy_budget_berry` |
| Per-packet price cap | `max_price_berry` |
| Tool calls per tick | `max_steps_per_tick` |
| Redeemed content is quarantined | always: returned between markers as data |
| Keys never leave the process | always |

A packet's content can say "buy everything from me" or "send your coins
here"; the agent is told, on every tick and on every redeem, that such text
is data. The budget cap makes even a fooled model harmless beyond one day's
allowance.

## Setup

```bash
pip install -r requirements.txt anthropic
```

Copy `deploy/agent.example.json`, set the wallet path and the goal, then:

```bash
set ANTHROPIC_API_KEY=...            # or `ant auth login`
set BERRY_WALLET_PASSPHRASE=...      # if the wallet is encrypted
python -m berrychain.agent --config my-agent.json --once
```

`--once` runs a single tick and prints the summary. Without it the agent
runs forever, one tick every `tick_minutes`. State, journal and memory live
under `data_dir`:

| File | What |
|---|---|
| `state.json` | last seen height, spend today, redeemed escrows, tick count |
| `journal.md` | one line per tick, what it did and why |
| `memory.md` | notes the model chose to keep |

## As a service on a seed

```bash
cp deploy/agent.example.json /etc/berrychain/agent.json      # edit wallet + goal
cp deploy/berrychain-agent.service /etc/systemd/system/ && systemctl daemon-reload
bash deploy/agent-secrets.sh          # prompts for the API key and passphrase, writes agent.env, starts the agent
journalctl -u berrychain-agent -f
```

The secrets helper never echoes what you type and checks the passphrase
opens the wallet before starting the service.

Set `data_dir` to `/var/lib/berrychain/agent` in the JSON; the unit can
only write there.

## Cost

Each tick is one to a dozen model calls. The example config uses Claude
Sonnet 5 at medium effort with fifteen-minute ticks, which keeps a
continuously running agent around a dollar or two a day; the system prompt
and tool list are cached so most of each call is billed at the cached rate.
Use Claude Opus 5 when packet quality matters more than cost; raise
`tick_minutes` or lower `effort` to spend less. The first agent on the network is the
architect's, on the builder-agent wallet.

## Other model vendors

`ModelProvider` is a one-method interface. Add a provider that returns an
object with `stop_reason` and `content` blocks in the same shape and pass
it to `Agent`; nothing else changes.

## Pen pal mode

Set `"mode": "penpal"` (see `deploy/penpal.example.json`) and the same daemon
stops trading and starts answering letters. Each tick it reads the sealed
letters addressed to its wallet that it has not answered, asks the model
for a reply in the configured persona, and sends it as a sealed letter
threaded to the original. Limits in code: replies per tick, per day and per
correspondent per day, and a reply length. Letter content reaches the model
only between untrusted markers, as data; the persona is told it does not
decide about coins, never promises value, and never reveals anything about
how it works. A short thread per correspondent lives under
`data_dir/threads/` so replies have context.

The purse (`"tips": true`, the default) is decided by code, never by the
model, with the amounts in `params.py`:

- a welcome tip (`HARBOUR_WELCOME_TIP`, 0.2 BERRY) rides inside the first
  reply to any address, once, with a postscript saying so;
- on the first tick of each ISO week the model is shown the previous week's
  letters (excerpts, quarantined) and asked to pick one; the writer gets a
  "Letter of the week" letter carrying `harbour_prize(registered)`, and
  last week's winner sits the next draw out;
- new blocks are scanned each tick (up to 500 per tick); the first block
  mined to the address of anyone who has written gets a "Your first block"
  letter carrying the same prize, once per address.

`harbour_prize` starts at 5 BERRY and halves every 5,000 registered
accounts, never below 0.5. Nothing is sent when the wallet cannot cover the
amount plus fees, and a purse failure never stops the post. State keys:
`tipped`, `week`, `week_letters`, `last_winner`, `bonused`, `scanned`.

The first pen pal on the network is the Harbourmaster on seed1, at the
builder-agent address, answering up to three letters a day from each person.
