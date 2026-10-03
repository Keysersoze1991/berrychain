#!/usr/bin/env python3
"""Set keys in /etc/berrychain/agent.json from the command line, as root:

    python3 /opt/berrychain/deploy/agent-config.py steward_address=brry1... founding_claims_alert_per_day=5

Values that look like integers are stored as integers, 'true'/'false' as booleans,
anything else as a string. Prints the keys it changed."""
import json
import sys

PATH = "/etc/berrychain/agent.json"


def parse(v: str):
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    try:
        return int(v)
    except ValueError:
        return v


def main(argv):
    if not argv or any("=" not in a for a in argv):
        print(__doc__)
        return 2
    with open(PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    for a in argv:
        k, v = a.split("=", 1)
        cfg[k] = parse(v)
        print(f"{k} = {cfg[k]!r}")
    with open(PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
