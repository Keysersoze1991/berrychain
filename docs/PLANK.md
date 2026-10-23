# Walk the Plank

The captain's daily trivia dive, at [berrychain.link/plank](https://berrychain.link/plank/).
Seven prompts a day, the same seven for everyone, 25 seconds each. An answer is
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
  rough order of popularity, aliases joined with `=`. The first eight listed
  answers carry a prior weight (20, 12, 8, 5, 4, 3, 3, 2; the rest 1) so day one
  scores sensibly before the crew's own answers take over. A prompt's id is a
  hash of its text, so reordering the file keeps the counts.
- `deploy/plank-setup.sh`: idempotent install (env, nginx location, unit).

## Endpoints

| route | what |
|---|---|
| `GET /plank/status` | prompt count, answers so far, today's date, whether the judge is on |
| `GET /plank/today?player=` | a session for today's seven (seeded by the UTC date) |
| `GET /plank/endless?player=` | a session for seven random prompts; not on the board |
| `POST /plank/answer` `{session, pid, answer, player}` | scores one answer, once per prompt per session |
| `GET /plank/board?day=` | the day's deepest named, completed dives (top 20) |
| `GET /plank/reveal?pid=` | the top eight answers to a prompt |

## Judging answers

An answer is matched against the prompt's list (aliases, plurals, small typos).
Anything else is put to a model once, with `ANTHROPIC_API_KEY` from
`/etc/berrychain/plank.env` (the setup script copies the key line from
`agent.env`). The verdict, valid with a canonical name or invalid, is cached per
spelling, so no spelling is judged twice. `PLANK_JUDGE_PER_DAY` caps the calls.
With no key the judge is off and unlisted answers score nothing, with the
message "the captain cannot rule on that one right now".

## Rewards

Decided, not yet built: 0.2 BERRY for passing 5,000 m on the daily plank, once
per day per registered name, paid from the race purse as a gift letter, the same
purse as MTB Crazy. The page says so and says BERRY has no price and no value.

## Privacy

The page sends the typed name, the answers and the day to seed1. Nothing else.
Names are shown on the day's crew board. State files are 0600, berry only.
