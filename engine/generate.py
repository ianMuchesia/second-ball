"""Generate one synthetic match as JSON lines (Match first, then events) on stdout.

uv run python -m engine.generate --home ashgrove --away ironvale --seed 1 --weather rain
"""

import argparse
import sys
from typing import get_args

from core.contracts.match import Weather
from engine.core import score, simulate_match
from engine.league import load_league


def main(argv=None):
    league = load_league()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--home", required=True, choices=sorted(league))
    parser.add_argument("--away", required=True, choices=sorted(league))
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--weather", default="dry", choices=get_args(Weather))
    args = parser.parse_args(argv)

    result = simulate_match(
        league[args.home], league[args.away], args.seed, weather=args.weather
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
