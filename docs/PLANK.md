# Walk the Plank

The captain's daily trivia dive, at [berrychain.link/plank](https://berrychain.link/plank/).
Seven prompts a day, the same seven for everyone, 25 seconds each. A prompt
used in the last 30 plank days is not drawn again (`NO_REPEAT_DAYS`, from
`NO_REPEAT_FROM` = 2026-11-11 on; the draw stays a pure function of the day and
the bank, no state). An answer is
scored by how rare it is among everything the crew has answered to that prompt:

| share of answers | points |
|---|---|
| 25% or more | 10 |
| 12% | 20 |
| 6% | 30 |
| 3% | 50 |
| 1% | 75 |
| under 1%, or never seen | 100 |

A point is ten metres. 7,000 m is a perfect plank: Shallows below 2,000, Reef to
3,500, Wreck to 5,000, Abyss to 6,500, then Davy Jones' Locker.

## Pieces

- `site/plank/`: the page. Static, no build. Talks to the service on seed1.
- `berrychain/plank.py`: the service, `python -m berrychain.plank`, bound to
  127.0.0.1:8805 and fronted by nginx at `/plank/`. State is one JSON file,
  `plank-state.json`, under `/var/lib/berrychain/plank`.
- `deploy/plank-prompts.txt`: the captain's log. One prompt per line, answers in
  rough order of popularity, aliases joined with `=`. A line starting with `=`
  is a single-answer question (`= Which continent has no Formula 1 race | Africa`):
  a right answer scores 100 whatever its rarity, a wrong one nothing, and the
  judge is told to accept only the same thing under another name. Each daily
  seven carries `FACT_PER_DAY` (2) of them. Open prompts: one per line, answers in
  rough order of popularity, aliases joined with `=`. The first eight listed
  answers carry a prior weight (20, 12, 8, 5, 4, 3, 3, 2; the rest 1) so day one
  scores sensibly before the crew's own answers take over. A prompt's id is a
  hash of its text, so reordering the file keeps the counts.
- `deploy/plank-setup.sh`: idempotent install (env, nginx location, unit).

## Endpoints

| route | what |
|---|---|
| `GET /plank/status` | prompt count, answers so far, today's date, whether the judge is on, whether the purse is open and what it pays |
| `GET /plank/today?player=` | a session for today's seven (seeded by the plank day: a new plank at 5 am Sydney time, `PLANK_TZ` / `PLANK_DAY_START_HOUR`) |
| `GET /plank/endless?player=` | a session for seven random prompts; not on the board |
| `POST /plank/answer` `{session, pid, answer, player}` | scores one answer, once per prompt per session |
| `GET /plank/board?day=` | the day's deepest named, completed dives, one row per name (top 20); `&range=week` gives the Monday-to-Sunday week of that day, each name's deepest dive and how many dives they made. Rows carry `named` when the name is a registered BerryChain name. |
| `GET /plank/reveal?pid=` | the top eight answers to a prompt |

The page opens with `?name=<registered name>` from the app (home screen, the
anchor on the Harbourmaster's purse card), which fills the name in.

## Judging answers

An answer is matched against the prompt's list (aliases, plurals, small typos).
Anything else is put to a model once (shown the prompt, the first eight listed
answers as examples of what is wanted, and the player's answer; told to accept
when in doubt and to reject only made-up, wrong-category, vague or rude
answers), with `ANTHROPIC_API_KEY` from
`/etc/berrychain/plank.env` (the setup script copies the key line from
`agent.env`). The verdict, valid with a canonical name or invalid, is cached per
spelling, so no spelling is judged twice. `PLANK_JUDGE_PER_DAY` caps the calls.
With no key the judge is off and unlisted answers score nothing, with the
message "the captain cannot rule on that one right now". After a judge change,
`PLANK_FORGET_INVALID=1 bash deploy/plank-setup.sh` drops the cached rejections
(`python -m berrychain.plank forget-invalid` with the service stopped) so those
spellings are judged afresh; past scores are not changed.

## The dive prize

0.2 BERRY (`PURSE_PLANK_DIVE`) for passing 5,000 m (`PLANK_PRIZE_DEPTH`) on the
daily plank, once per day per registered name. When the seventh answer of a
daily session lands deep enough, the service looks the player's name up in the
chain's registry (`/llms` on `PLANK_NODE_URL`, cached five minutes; `off` keeps
the purse shut). A name carried by exactly one account earns one file in
`PLANK_DIR/queue` (see `berrychain/purse.py`); the Harbourmaster pays it as a
gift letter on its next tick, under its daily cap. The answer response carries
`prize`: `{paid, amount, to, why}`, or just `{paid: false, why}` when the name
is missing, unregistered or already paid today (state key `dive_paid`, by day
and address). Typing someone else's registered name only sends the coins to
them. The endless plank never pays.

## Privacy

The page sends the typed name, the answers and the day to seed1. Nothing else.
Names are shown on the day's crew board. State files are 0600, berry only.
