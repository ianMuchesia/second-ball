"""secondball: generate synthetic football datasets.

    uv run secondball generate --matches 100 --seed 7 --out data/

Writes, for free-simulation matches (fictional clubs, synthetic only):
    <out>/matches.parquet        one row per match
    <out>/events.parquet         one row per event (freeze frame as a nested list)
    <out>/jsonl/<match_id>.jsonl Match then events, exactly the contract JSON
    <out>/engine_truth.parquet   engine-only labels per event (evals only)
    <out>/manifest.json          how the dataset was made
Same arguments = same data. See docs/DATASHEET.md.
"""

import argparse
import itertools
import json
import multiprocessing
import random
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import get_args

import pyarrow as pa
import pyarrow.parquet as pq

from core.contracts import SCHEMA_VERSION
from core.contracts.match import Weather
from engine.core import score, simulate_match
from engine.league import load_league

WEATHERS = get_args(Weather)

PLAYER = pa.struct(
    [
        ("player_id", pa.string()),
        ("team_id", pa.string()),
        ("x", pa.float64()),
        ("y", pa.float64()),
        ("facing_deg", pa.float64()),
    ]
)
EVENTS = pa.schema(
    [
        ("schema_version", pa.int32()),
        ("event_id", pa.string()),
        ("match_id", pa.string()),
        ("possession_id", pa.string()),
        ("period", pa.int32()),
        ("minute", pa.int32()),
        ("second", pa.int32()),
        ("team_id", pa.string()),
        ("player_id", pa.string()),
        ("type", pa.string()),
        ("outcome", pa.string()),
        ("body_part", pa.string()),
        ("start_x", pa.float64()),
        ("start_y", pa.float64()),
        ("end_x", pa.float64()),
        ("end_y", pa.float64()),
        ("under_pressure", pa.bool_()),
        ("ball_speed_kmh", pa.float64()),
        ("qualifiers", pa.string()),  # JSON object (mixed value types)
        ("freeze_frame", pa.list_(PLAYER)),
    ]
)
TRUTH = pa.schema(
    [
        ("match_id", pa.string()),
        ("event_id", pa.string()),
        ("labels", pa.string()),  # JSON object
    ]
)
MATCHES = pa.schema(
    [
        ("schema_version", pa.int32()),
        ("match_id", pa.string()),
        ("home_team", pa.string()),
        ("away_team", pa.string()),
        ("venue", pa.string()),
        ("kickoff", pa.string()),
        ("competition", pa.string()),
        ("seed", pa.int64()),
        ("weather", pa.string()),
        ("mode", pa.string()),
        ("home_goals", pa.int32()),
        ("away_goals", pa.int32()),
        ("events", pa.int32()),
    ]
)

# spawn, not fork: forking a multi-threaded process can deadlock.
SPAWN = multiprocessing.get_context("spawn")


def fixtures(matches, seed, weather):
    """(home, away, seed, weather) per match: ordered club pairs in turn."""
    clubs = sorted(load_league())
    pairs = itertools.cycle(itertools.permutations(clubs, 2))
    out = []
    for i, (home, away) in zip(range(matches), pairs, strict=False):
        s = seed + i
        w = random.Random(s).choice(WEATHERS) if weather == "mixed" else weather
        out.append((home, away, s, w))
    return out


def play(fixture):
    home, away, seed, weather = fixture
    league = load_league()
    result = simulate_match(league[home], league[away], seed, weather=weather)
    h, a = score(result)
    match_row = {
        **result.match.model_dump(mode="json"),
        "home_goals": h,
        "away_goals": a,
        "events": len(result.events),
    }
    event_rows = []
    lines = [result.match.model_dump_json()]
    for e in result.events:
        row = e.model_dump(mode="json")
        row["qualifiers"] = json.dumps(row["qualifiers"], sort_keys=True)
        event_rows.append(row)
        lines.append(e.model_dump_json())
    truth_rows = [
        {
            "match_id": result.match.match_id,
            "event_id": t["event_id"],
            "labels": json.dumps(
                {k: v for k, v in t.items() if k != "event_id"}, sort_keys=True
            ),
        }
        for t in result.truth
    ]
    return match_row, event_rows, lines, truth_rows


def generate(matches, seed, out, weather="dry", workers=None, jsonl=True):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    if jsonl:
        (out / "jsonl").mkdir(exist_ok=True)
    match_rows, truth_rows = [], []
    events_path = out / "events.parquet"
    total_events = 0
    with (
        ProcessPoolExecutor(max_workers=workers, mp_context=SPAWN) as pool,
        pq.ParquetWriter(events_path, EVENTS) as writer,
    ):
        for match_row, event_rows, lines, truth in pool.map(
            play, fixtures(matches, seed, weather)
        ):
            match_rows.append(match_row)
            truth_rows.extend(truth)
            writer.write_table(pa.Table.from_pylist(event_rows, schema=EVENTS))
            total_events += len(event_rows)
            if jsonl:
                path = out / "jsonl" / f"{match_row['match_id']}.jsonl"
                path.write_text("\n".join(lines) + "\n")
    pq.write_table(
        pa.Table.from_pylist(match_rows, schema=MATCHES), out / "matches.parquet"
    )
    pq.write_table(
        pa.Table.from_pylist(truth_rows, schema=TRUTH), out / "engine_truth.parquet"
    )
    manifest = {
        "generator": "secondball generate",
        "schema_version": SCHEMA_VERSION,
        "mode": "free_simulation",
        "matches": matches,
        "events": total_events,
        "first_seed": seed,
        "weather": weather,
        "clubs": sorted(load_league()),
        "files": ["matches.parquet", "events.parquet", "engine_truth.parquet"]
        + (["jsonl/<match_id>.jsonl"] if jsonl else []),
        "datasheet": "docs/DATASHEET.md",
        "synthetic": True,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="secondball", description=__doc__.splitlines()[0]
    )
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("generate", help="generate free-simulation matches")
    gen.add_argument("--matches", type=int, required=True)
    gen.add_argument(
        "--seed", type=int, required=True, help="first seed; match i uses seed + i"
    )
    gen.add_argument("--out", type=Path, required=True)
    gen.add_argument("--weather", default="dry", choices=[*WEATHERS, "mixed"])
    gen.add_argument("--workers", type=int, default=None)
    gen.add_argument(
        "--no-jsonl", action="store_true", help="Parquet only (much smaller)"
    )
    args = parser.parse_args(argv)

    if args.matches < 1:
        parser.error("--matches must be at least 1")
    manifest = generate(
        args.matches, args.seed, args.out, args.weather, args.workers, not args.no_jsonl
    )
    print(
        f"wrote {manifest['matches']} matches, {manifest['events']} events to {args.out}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
