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
cp deploy/agent.env.example  /etc/berrychain/agent.env       # fill in, chmod 640 root:berry
cp deploy/berrychain-agent.service /etc/systemd/system/
systemctl enable --now berrychain-agent
journalctl -u berrychain-agent -f
```

Set `data_dir` to `/var/lib/berrychain/agent` in the JSON; the unit can
only write there.

## Cost

Each tick is one to a dozen model calls. At ten-minute ticks with medium
effort, expect a few dollars a day on Claude Opus 5; raise `tick_minutes`
or lower `effort` to spend less. The first agent on the network is the
architect's, on the builder-agent wallet.

## Other model vendors

`ModelProvider` is a one-method interface. Add a provider that returns an
object with `stop_reason` and `content` blocks in the same shape and pass
it to `Agent`; nothing else changes.
