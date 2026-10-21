"""Generate one synthetic match as JSON lines (Match first, then events) on stdout.

uv run python -m engine.generate --home ashgrove --away ironvale --seed 1 --weather rain
uv run python -m engine.generate --demo
"""

import argparse
import sys
from datetime import datetime, timedelta, timezone
from typing import get_args

from core.contracts.match import Weather
from engine.core import score, simulate_match
from engine.league import load_league

NAIROBI = timezone(timedelta(hours=3))
# Demo match (Ian, 2026-10-20). Date and seed chosen by the agent; change freely.
DEMO = {
    "home": "riverside_athletic",
    "away": "ironvale",
    "seed": 1,
    "weather": "dry",
    "kickoff": datetime(2026, 11, 7, 15, 0, tzinfo=NAIROBI),
}


def main(argv=None):
    league = load_league()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--demo", action="store_true", help="the demo match")
    parser.add_argument("--home", choices=sorted(league))
    parser.add_argument("--away", choices=sorted(league))
    parser.add_argument("--seed", type=int)
    parser.add_argument("--weather", default="dry", choices=get_args(Weather))
    args = parser.parse_args(argv)
    if args.demo:
        for k, v in DEMO.items():
            setattr(args, k, v)
    elif None in (args.home, args.away, args.seed):
        parser.error("--home, --away and --seed are required (or use --demo)")

    kwargs = {"kickoff": args.kickoff} if args.demo else {}
    result = simulate_match(
        league[args.home], league[args.away], args.seed, weather=args.weather, **kwargs
    )
    print(result.match.model_dump_json())
    for event in result.events:
        print(event.model_dump_json())
    home, away = score(result)
    print(
        f"{args.home} {home}-{away} {args.away}, {len(result.events)} events",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
