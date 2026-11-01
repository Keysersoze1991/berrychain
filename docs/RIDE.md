# MTB Crazy

A pirate on a mountain bike, side-on stunt racing, at
[berrychain.link/ride](https://berrychain.link/ride/). Twenty courses in four
tiers. Flips, loops you jump into and big air take time off the clock. The game
runs entirely in the page; only a record claim is sent anywhere.

## Pieces

- `site/ride/engine.js`: the track builder, the twenty generated courses and the
  fixed-step physics (60 Hz, Verlet, one-sided segments). No DOM. Loaded by the
  page as `window.MTB` and by the referee under Node. Every run is its input log,
  one five-bit mask per tick (1 pedal, 2 brake, 4 back, 8 forward, 16 sprint);
  on the wire a log is a string from `LOG_CHARS`, one character per tick.
- `site/ride/game.js`: drawing, input, menus, best times on the device, and the
  record board (fetches `/ride/board`, posts `/ride/claim`).
- `site/ride/check.js`: the referee's command line. `node check.js` reads
  `{"level", "log"}` on stdin and prints what the clock said after replaying the
  run on the same engine; `--courses` lists the courses.
- `berrychain/ride.py`: the record board service, `python -m berrychain.ride`,
  bound to 127.0.0.1:8806 and fronted by nginx at `/ride/` on seed1. State is
  one JSON file, `ride-state.json`, under `/var/lib/berrychain/ride`. Needs
  Node on the seed (`RIDE_NODE`, `RIDE_CHECK` in `ride.env`).
- `deploy/ride-setup.sh`: idempotent install (env, nginx location, unit).

## Endpoints

| route | what |
|---|---|
| `GET /ride/status` | courses, records held, today's date, what the purse pays |
| `GET /ride/board` | the twenty courses with the record on each: name, time in ticks, whether it was set under a registered name, the day |
| `POST /ride/claim` `{level, name, addr, log}` | judges a run; if it beats the record it becomes the record |

A claim is never taken on the player's word. The service replays the log with
Node (one replay at a time, twenty seconds at most, sixty claims a minute) and
the replayed time is the only time that counts. A run that never reaches the
flag, a malformed log or a log over 24,000 ticks is refused before Node runs.
If Node cannot run, the claim is answered 503 and nothing changes. The winning
log is kept in the state file so a record can be checked again later. Replays
match the page because both run the same script on V8; a browser whose maths
library rounds `sin`/`cos` differently could in principle diverge over a long
run, in which case the referee's figure stands.

The app (from 0.16) opens the page as `/ride/?name=<registered name>&addr=<address>`
from the small penny-farthing at the foot of the home screen, which fills the
claim form in; the plank link is the anchor on the purse card.

## The purse

Whoever holds a course record holds that course's purse, paid when the record
changes hands:

- 0.2 BERRY (`PURSE_RIDE_RECORD`) to the address given with the claim;
- 2 BERRY (`PURSE_RIDE_NAMED`) when the name on the board is a registered
  BerryChain name and the claim's address carries it. A registered name alone
  is enough: the service looks it up (`/llms` on `RIDE_NODE_URL`, cached five
  minutes) and pays that address, provided exactly one account carries the name.

Nothing is paid when the same address merely improves its own record, when the
course has already paid out today (UTC), or when no address is given (the
record stands, the coins stay in the purse). Each prize is one file in
`RIDE_DIR/queue`; the Harbourmaster pays it as a gift letter on its next tick
under its daily cap (`berrychain/purse.py`, `docs/STANDING_AGENT.md`). The
page says BERRY has no price and no value.

## Privacy

The page sends nothing while you play. A claim sends the course number, the
name typed, the address typed (optional) and the key presses of that one run.
Names and times are shown on the board; addresses are not. State files are
0600, berry only.
