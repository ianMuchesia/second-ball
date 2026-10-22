"""Learn the metric artifacts from free_simulation matches (events only).

    uv run python -m scripts.fit_metrics            # xT grid + openness baseline
    uv run python -m scripts.fit_metrics --report   # only print the distributions

1. xT grid by value iteration on 500 matches -> core/metrics/artifacts/xt_v1.json
2. Openness baseline: the openness index of every 10-minute window (one per
   minute from 10') in 500 other matches, averaged per pre-match strength-gap
   bucket -> core/metrics/artifacts/openness_baseline_v1.json

The engine only generates the matches; the fitting code (core/metrics) sees
MatchEvents and the Match's public strengths, nothing else.
"""

import argparse
import hashlib
import json
import multiprocessing
import statistics
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from core.metrics import Events, chaos, xt
from core.metrics.registry import start_index
from engine.core import simulate_match
from engine.league import load_league
from evals.realism.report import fixtures

ROOT = Path(__file__).resolve().parent.parent
XT_MATCHES, XT_FIRST_SEED = 500, 70_000
BASELINE_MATCHES, BASELINE_FIRST_SEED = 500, 80_000
WINDOW = 10


def light(e):
    """The event without its freeze frame (not needed here; saves memory)."""
    return e.model_copy(update={"freeze_frame": e.freeze_frame[:1]})


def play(fixture):
    home, away, seed = fixture
    league = load_league()
    m = simulate_match(league[home], league[away], seed)
    return m.match, [light(e) for e in m.events]


def simulate(n, first_seed):
    with ProcessPoolExecutor(mp_context=multiprocessing.get_context("spawn")) as pool:
        return list(pool.map(play, fixtures(n, first_seed), chunksize=8))


def windows(match, events, minutes=WINDOW):
    """Openness parts for each 10-minute window ending at each full minute."""
    ev = Events.for_match(match)
    out, nxt = [], minutes * 60
    for e in events:
        ev.append(e)
        if ev.now() >= nxt:
            lo = start_index(ev, minutes)
            out.append(
                {
                    "openness": chaos.openness_index(ev, lo),
                    "two_way": chaos.two_way_threat(ev, lo),
                    "switches": chaos.threat_switches(ev, lo),
                    "speed": chaos.transition_speed(ev, lo),
                }
            )
            nxt += 60
    return out


def match_windows(args):
    return windows(*args)


def pct(values, q):
    values = sorted(values)
    return values[min(len(values) - 1, int(q * len(values)))]


def config_hash():
    return hashlib.sha256(
        (ROOT / "engine" / "config" / "engine.yaml").read_bytes()
    ).hexdigest()[:12]


def fit_xt():
    played = simulate(XT_MATCHES, XT_FIRST_SEED)
    values, iterations = xt.fit(events for _, events in played)
    path = xt.save(
        values,
        {
            "mode": "free_simulation",
            "matches": XT_MATCHES,
            "first_seed": XT_FIRST_SEED,
            "events": sum(len(e) for _, e in played),
            "iterations": iterations,
            "engine_config_sha256_12": config_hash(),
            "date": datetime.now(UTC).date().isoformat(),
        },
    )
    print(f"xT: {iterations} iterations -> {path.relative_to(ROOT)}")
    xt.load.cache_clear()


def fit_baseline(report_only):
    played = simulate(BASELINE_MATCHES, BASELINE_FIRST_SEED)
    with ProcessPoolExecutor(mp_context=multiprocessing.get_context("spawn")) as pool:
        per_match = list(pool.map(match_windows, played, chunksize=8))
    flat = [w for ws in per_match for w in ws]
    for part in ("two_way", "switches", "speed"):
        vals = [w[part].value for w in flat if w[part] is not None]
        print(
            f"{part}: n={len(vals)} p50={pct(vals, 0.5):.3f} p75={pct(vals, 0.75):.3f} "
            f"p90={pct(vals, 0.9):.3f} p10={pct(vals, 0.1):.3f}"
        )
    if report_only:
        return
    buckets = {}
    for (match, _), ws in zip(played, per_match, strict=True):
        gap = abs(match.home_strength - match.away_strength)
        b = buckets.setdefault(chaos.gap_bucket(gap), {"matches": 0, "values": []})
        b["matches"] += 1
        b["values"] += [w["openness"].value for w in ws if w["openness"] is not None]
    out = {
        "version": chaos.config()["openness"]["baseline_version"],
        "metric": "openness_index (rolling 10 min, one window per minute from 10')",
        "trained_on": {
            "mode": "free_simulation",
            "matches": BASELINE_MATCHES,
            "first_seed": BASELINE_FIRST_SEED,
            "xt_version": chaos.config()["xt_version"],
            "engine_config_sha256_12": config_hash(),
            "date": datetime.now(UTC).date().isoformat(),
        },
        "buckets": {
            name: {
                "matches": b["matches"],
                "windows": len(b["values"]),
                "mean": round(statistics.fmean(b["values"]), 4),
                "sd": round(statistics.pstdev(b["values"]), 4),
            }
            for name, b in sorted(buckets.items())
        },
    }
    path = (
        ROOT
        / "core"
        / "metrics"
        / "artifacts"
        / f"openness_baseline_v{out['version']}.json"
    )
    path.write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out["buckets"], indent=1))
    print(f"baseline -> {path.relative_to(ROOT)}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--report", action="store_true", help="only print distributions"
    )
    parser.add_argument(
        "--skip-xt", action="store_true", help="keep the current xT grid"
    )
    args = parser.parse_args(argv)
    if not args.report and not args.skip_xt:
        fit_xt()
    fit_baseline(args.report)


if __name__ == "__main__":
    main()
