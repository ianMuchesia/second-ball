"""Calibrate the physics-first engine: the same fixed seeds, every time.

    uv run python -m evals.physics_calibration --seeds 10 --label baseline

Plays Riverside v Harbour (the demo fixture) on the physics engine for the
given seeds (4 at a time), measures each team separately and prints it
against the acceptance targets, which were set before any tuning from the
sourced realism report (docs/DATA_REALISM.md: the two clubs' own rows and the
league bands) and the behaviour reference (docs/FOOTBALL_BEHAVIOUR.md, s.14).
Results are appended to evals/physics_calibration.jsonl, one line per run.
"""

import argparse
import json
import math
import statistics
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from multiprocessing import get_context
from pathlib import Path

HOME, AWAY = "riverside_athletic", "harbour_town"
LOG = Path(__file__).with_name("physics_calibration.jsonl")

# (low, high) acceptance per match; None = reported, not gating yet.
TARGETS = {
    "home_goals": (1.5, 2.5),
    "away_goals": (0.3, 1.2),
    "home_shots": (12.0, 22.0),
    "away_shots": (4.0, 10.0),
    "home_possession": (0.52, 0.62),
    "passes": (750.0, 1050.0),
    "pass_completion": (0.78, 0.86),
    "on_target_share": (0.34, 0.38),
    "xg_per_shot": (0.11, 0.14),
    "home_ppda": None,  # ~9.4 (club row)
    "away_ppda": None,  # ~20.7
    "corners": None,  # ~10
    "throw_ins": None,  # ~40
    "goal_kicks": None,  # 20-30
    "long_balls": None,  # ~95-100
    "tackles": None,
    "interceptions": None,
}


def play(seed):
    from engine.league import load_league
    from engine.play.match import simulate_physics_match

    league = load_league()
    r = simulate_physics_match(league[HOME], league[AWAY], seed)
    return measure(r)


def measure(r):
    ev = r.events
    out = {}
    for side, team in (("home", HOME), ("away", AWAY)):
        mine = [e for e in ev if e.team_id == team]
        shots = [e for e in mine if e.type.startswith("shot")]
        out[f"{side}_goals"] = sum(e.outcome == "success" for e in shots)
        out[f"{side}_shots"] = len(shots)
        out[f"{side}_on_target"] = sum(
            e.outcome == "success" or e.qualifiers.get("result") == "saved"
            for e in shots
        )
        out[f"{side}_xg"] = sum(e.qualifiers.get("xg", 0.0) for e in shots)
        out[f"{side}_passes"] = sum(e.type == "pass" for e in mine)
        out[f"{side}_passes_ok"] = sum(
            e.type == "pass" and e.outcome == "success" for e in mine
        )
        # PPDA: the opponent's passes in its own 60% / our defensive actions there.
        their = [e for e in ev if e.team_id != team]
        opp_passes = sum(1 for e in their if e.type == "pass" and e.start_x < 63.0)
        actions = sum(
            1
            for e in mine
            if e.type in ("tackle", "interception", "foul") and e.start_x > 42.0
        )
        out[f"{side}_ppda"] = opp_passes / actions if actions else float("nan")
    passes = out["home_passes"] + out["away_passes"]
    shots = out["home_shots"] + out["away_shots"]
    out["home_possession"] = out["home_passes"] / passes if passes else float("nan")
    out["passes"] = passes
    out["pass_completion"] = (out["home_passes_ok"] + out["away_passes_ok"]) / passes
    out["on_target_share"] = (
        (out["home_on_target"] + out["away_on_target"]) / shots if shots else 0
    )
    out["xg_per_shot"] = (out["home_xg"] + out["away_xg"]) / shots if shots else 0
    out["corners"] = sum(e.type == "corner_crossed" for e in ev)
    out["throw_ins"] = sum(e.type == "throw_in" for e in ev)
    out["goal_kicks"] = sum(e.type == "goalkick" for e in ev)
    out["long_balls"] = sum(
        1
        for e in ev
        if e.type == "pass"
        and math.dist((e.start_x, e.start_y), (e.end_x, e.end_y)) > 30
    )
    out["tackles"] = sum(e.type == "tackle" for e in ev)
    out["interceptions"] = sum(e.type == "interception" for e in ev)
    return out


def summarise(rows):
    keys = list(TARGETS)
    return {k: statistics.mean(r[k] for r in rows) for k in keys}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--seeds", type=int, default=10)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--label", default="run")
    args = p.parse_args(argv)
    seeds = list(range(1, args.seeds + 1))
    with ProcessPoolExecutor(args.workers, mp_context=get_context("spawn")) as pool:
        rows = list(pool.map(play, seeds))
    mean = summarise(rows)
    print(f"{args.label}: {len(rows)} matches (seeds {seeds[0]}-{seeds[-1]})")
    print(f"  scores: {[f'{r["home_goals"]}-{r["away_goals"]}' for r in rows]}")
    passed = 0
    gated = 0
    for k, band in TARGETS.items():
        v = mean[k]
        if band is None:
            print(f"  {k:18s} {v:8.3f}   (reported)")
            continue
        gated += 1
        ok = band[0] <= v <= band[1]
        passed += ok
        print(
            f"  {k:18s} {v:8.3f}   target {band[0]}-{band[1]}   {'PASS' if ok else 'FAIL'}"
        )
    print(f"  {passed}/{gated} gated targets met")
    with LOG.open("a") as f:
        f.write(
            json.dumps(
                {
                    "label": args.label,
                    "at": datetime.now(UTC).isoformat(),
                    "seeds": seeds,
                    "mean": mean,
                    "scores": [[r["home_goals"], r["away_goals"]] for r in rows],
                }
            )
            + "\n"
        )


if __name__ == "__main__":
    main()
