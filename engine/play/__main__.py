"""Run a drill or an attack and save it as a run bundle the screen plays.

uv run python -m engine.play --seed 3 --out runs/drill-3            # Stage 1
uv run python -m engine.play --attack --seed 76 --out runs/attack-76  # Stage 2
"""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from engine.core import trackfile
from engine.league import load_league
from engine.play.drill import run_drill
from engine.play.game import run_attack

EMPTY = [
    "moments.jsonl",
    "overlays.jsonl",
    "narrations.jsonl",
    "indicators.jsonl",
    "traces.jsonl",
    "player_recaps.jsonl",
]


def write_run(result, folder: Path, name: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "match.json").write_text(result.match.model_dump_json(indent=1))
    with (folder / "events.jsonl").open("w") as f:
        for e in result.events:
            f.write(e.model_dump_json() + "\n")
    trackfile.write(result.tracks, folder)
    for empty in EMPTY:
        (folder / empty).write_text("")
    meta = {
        "name": name,
        "match_id": result.match.match_id,
        "mode": "drill",
        "recorded_at": datetime.now(UTC).isoformat(),
        "model": "none",
        "languages": ["en"],
        "shipped_languages": ["en"],
        "model_calls": 0,
        "usd": 0.0,
        "kes": 0,
        "how": "physics-first engine (no commentary)",
        "outcome": result.outcome,
    }
    (folder / "meta.json").write_text(json.dumps(meta, indent=1) + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--attack", action="store_true", help="Stage 2: the attack")
    parser.add_argument("--home", default="riverside_athletic")
    parser.add_argument("--away", default="harbour_town")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    league = load_league()
    play = run_attack if args.attack else run_drill
    result = play(league[args.home], league[args.away], args.seed)
    write_run(result, args.out, args.out.name)
    print(
        f"{args.out}: {result.outcome}, {len(result.events)} events, "
        f"{len(result.tracks.samples)} samples"
    )


if __name__ == "__main__":
    main()
