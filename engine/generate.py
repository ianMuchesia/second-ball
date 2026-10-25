"""Generate one synthetic match.

Free simulation, JSON lines (Match first, then events) on stdout:
    uv run python -m engine.generate --home ashgrove --away ironvale --seed 1 --weather rain

Scenario (scripted beats), writes <out>/match.jsonl, <out>/expected_moments.json and
<out>/engine_truth.jsonl (engine-only labels; evals only, never the analyser):
    uv run python -m engine.generate --scenario demo_riverside_harbour --out demo
    uv run python -m engine.generate --demo --out demo

ENGINE=physics: the physics-first engine (engine/play/match.py) plays the
match instead (same files, plus the 10 Hz tracks). Its storyline beats are not
scripted yet, so a scenario's teams, seed and weather are used, its beats not:
    ENGINE=physics uv run python -m engine.generate --demo --out demo-physics
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import get_args

from core.contracts.match import Weather
from engine.core import score, simulate_match, trackfile
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

    if os.environ.get("ENGINE") == "physics":
        return physics(league, args, parser)
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
            tracks=True,  # recorded runs carry the 10 Hz movement
        )
        args.out.mkdir(parents=True, exist_ok=True)
        with (args.out / "match.jsonl").open("w") as f:
            write_lines(result, f)
        trackfile.write(result.tracks, args.out)
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


def physics(league, args, parser):
    """ENGINE=physics: the whole match on the physics-first engine."""
    from engine.play.match import simulate_physics_match

    if args.scenario:
        if args.out is None:
            parser.error("--out is required for a scenario")
        sc = load_scenario(args.scenario)
        home, away, seed, weather = sc.home, sc.away, sc.seed, sc.weather
        kickoff = sc.kickoff
    else:
        if None in (args.home, args.away, args.seed):
            parser.error("--home, --away and --seed are required (or use --scenario)")
        home, away, seed, weather = args.home, args.away, args.seed, args.weather
        kickoff = None
    extra = {"kickoff": kickoff} if kickoff else {}
    result = simulate_physics_match(
        league[home], league[away], seed, weather=weather, **extra
    )
    if args.out is None:
        write_lines(result, sys.stdout)
        return
    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "match.jsonl").open("w") as f:
        write_lines(result, f)
    trackfile.write(result.tracks, args.out)
    (args.out / "engine_truth.jsonl").write_text("")
    goals = [
        e for e in result.events if e.type.startswith("shot") and e.outcome == "success"
    ]
    h = sum(1 for e in goals if e.team_id == result.match.home_team)
    print(
        f"{args.out}: physics engine, {h}-{len(goals) - h}, {len(result.events)} events"
    )


if __name__ == "__main__":
    main()
