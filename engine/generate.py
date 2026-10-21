"""Generate one synthetic match.

Free simulation, JSON lines (Match first, then events) on stdout:
    uv run python -m engine.generate --home ashgrove --away ironvale --seed 1 --weather rain

Scenario (scripted beats), writes <out>/match.jsonl, <out>/expected_moments.json and
<out>/engine_truth.jsonl (engine-only labels; evals only, never the analyser):
    uv run python -m engine.generate --scenario demo_riverside_harbour --out demo
    uv run python -m engine.generate --demo --out demo
"""

import argparse
import json
import sys
from pathlib import Path
from typing import get_args

from core.contracts.match import Weather
from engine.core import score, simulate_match
from engine.league import load_league
from engine.scenarios import SCENARIOS_DIR, expected_moments, load_scenario

DEMO_SCENARIO = "demo_riverside_harbour"


def write_lines(result, out):
    out.write(result.match.model_dump_json() + "\n")
    for event in result.events:
        out.write(event.model_dump_json() + "\n")


def main(argv=None):
    league = load_league()
    scenarios = sorted(p.stem for p in SCENARIOS_DIR.glob("*.yaml"))
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--demo", action="store_true", help=f"= --scenario {DEMO_SCENARIO}"
    )
    parser.add_argument("--scenario", choices=scenarios)
    parser.add_argument("--out", type=Path, help="output folder (scenario mode)")
    parser.add_argument("--home", choices=sorted(league))
    parser.add_argument("--away", choices=sorted(league))
    parser.add_argument("--seed", type=int)
    parser.add_argument("--weather", default="dry", choices=get_args(Weather))
    args = parser.parse_args(argv)
    if args.demo:
        args.scenario = DEMO_SCENARIO

    if args.scenario:
        if args.out is None:
            parser.error("--out is required for a scenario")
        sc = load_scenario(args.scenario)
        result = simulate_match(
            league[sc.home],
            league[sc.away],
            sc.seed,
            weather=sc.weather,
            kickoff=sc.kickoff,
            scenario=sc,
        )
        args.out.mkdir(parents=True, exist_ok=True)
        with (args.out / "match.jsonl").open("w") as f:
            write_lines(result, f)
        with (args.out / "engine_truth.jsonl").open("w") as f:
            for row in result.truth:
                f.write(json.dumps(row, sort_keys=True) + "\n")
        key = expected_moments(sc, result.match)
        (args.out / "expected_moments.json").write_text(
            json.dumps(key, indent=2) + "\n"
        )
    else:
        if None in (args.home, args.away, args.seed):
            parser.error("--home, --away and --seed are required (or use --scenario)")
        result = simulate_match(
            league[args.home], league[args.away], args.seed, weather=args.weather
        )
        write_lines(result, sys.stdout)

    home, away = score(result)
    m = result.match
    print(
        f"[{m.mode}] {m.home_team} {home}-{away} {m.away_team}, {len(result.events)} events",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
