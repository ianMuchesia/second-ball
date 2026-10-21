"""Realism report: 500 free-simulation matches vs real reference bands.

    uv run python -m evals.realism.report        # or: make realism

Writes docs/DATA_REALISM.md. A metric passes when the simulated value's 95%
interval (bootstrap over matches) lies inside the reference band from
evals/realism/reference.yaml. Metrics without a current free source are shown
as "no reference", never compared against a remembered number.
"""

import itertools
import multiprocessing
import random
import statistics
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import yaml

from engine.core import simulate_match
from engine.league import load_league

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
REFERENCE = HERE / "reference.yaml"
REPORT = ROOT / "docs" / "DATA_REALISM.md"

MATCHES = 500
FIRST_SEED = 10_000
HOLDOUT_FIRST_SEED = 50_000  # never used for tuning
BOOTSTRAP = 2000
SHOTS = {"shot", "shot_freekick", "shot_penalty"}
# Throw-ins are not counted as passes (standard event-data practice).
PASSES = {
    "pass",
    "cross",
    "goalkick",
    "freekick_short",
    "freekick_crossed",
    "corner_crossed",
    "corner_short",
}
OPEN_PLAY_PASSES = {"pass", "cross"}
DEFENSIVE_ACTIONS = {"tackle", "interception", "foul"}
PPDA_ZONE_X = 63.0  # the passing team's own 60% (its frame)
LENGTH = 105.0

# spawn, not fork: forking a multi-threaded process can deadlock.
SPAWN = multiprocessing.get_context("spawn")


def fixtures(n=MATCHES, first_seed=FIRST_SEED):
    """(home, away, seed): every ordered pair of clubs in turn, fixed seeds."""
    clubs = sorted(load_league())
    pairs = itertools.cycle(itertools.permutations(clubs, 2))
    return [(h, a, first_seed + i) for i, (h, a) in zip(range(n), pairs, strict=False)]


def summarise(fixture):
    """Per-match totals (and per-team totals) from one simulated match."""
    home, away, seed = fixture
    league = load_league()
    m = simulate_match(league[home], league[away], seed)
    ev = m.events
    teams = (home, away)
    s = Counter()
    team = {t: Counter() for t in teams}
    for i, e in enumerate(ev):
        t = team[e.team_id]
        if e.type in SHOTS:
            nxt = ev[i + 1] if i + 1 < len(ev) else None
            on_target = e.outcome == "success" or (
                nxt is not None and nxt.type == "keeper_save"
            )
            s["shots"] += 1
            s["on_target"] += on_target
            s["xg"] += e.qualifiers.get("xg", 0.0)
            s["goals"] += e.outcome == "success"
            t["goals"] += e.outcome == "success"
            t["shots"] += 1
        if e.type in PASSES:
            s["passes"] += 1
            s["passes_ok"] += e.outcome == "success"
            t["passes"] += 1
        if e.type in OPEN_PLAY_PASSES and e.start_x < PPDA_ZONE_X:
            t["passes_in_own_60"] += 1
        if e.type in DEFENSIVE_ACTIONS and e.start_x > LENGTH - PPDA_ZONE_X:
            t["def_actions_high"] += 1
        if e.type == "corner_crossed":
            s["corners"] += 1
        if e.type == "foul":
            s["fouls"] += 1
            s["yellows"] += e.outcome == "yellow_card"
            s["reds"] += e.outcome == "red_card"
    s["matches"] = 1
    for me, opp in ((home, away), (away, home)):
        team[me]["ppda_passes"] = team[opp]["passes_in_own_60"]
        team[me]["ppda_actions"] = team[me]["def_actions_high"]
        team[me]["opp_passes"] = team[opp]["passes"]
    return dict(s), {k: dict(v) for k, v in team.items()}


def metric_values(sample):
    """All metrics from a list of per-match summaries (same maths as the reference)."""
    tot = Counter()
    clubs = {}
    for s, teams in sample:
        tot.update(s)
        for club, t in teams.items():
            clubs.setdefault(club, Counter()).update(t)
            clubs[club]["matches"] += 1
    n = tot["matches"]
    possession = [
        c["passes"] / (c["passes"] + c["opp_passes"])
        for c in clubs.values()
        if c["passes"]
    ]
    per_club_shots = [c["shots"] / c["matches"] for c in clubs.values()]
    ppda_passes = sum(c["ppda_passes"] for c in clubs.values())
    ppda_actions = sum(c["ppda_actions"] for c in clubs.values())
    return {
        "goals_per_match": tot["goals"] / n,
        "shots_per_match": tot["shots"] / n,
        "on_target_share": tot["on_target"] / tot["shots"],
        "xg_per_shot": tot["xg"] / tot["shots"],
        "fouls_per_match": tot["fouls"] / n,
        "corners_per_match": tot["corners"] / n,
        "yellow_cards_per_match": tot["yellows"] / n,
        "red_cards_per_match": tot["reds"] / n,
        "ppda": ppda_passes / ppda_actions,
        "pass_completion": tot["passes_ok"] / tot["passes"],
        "passes_per_match": tot["passes"] / n,
        "possession_spread": statistics.pstdev(possession),
        "team_shots_per_match": statistics.mean(per_club_shots),
        "team_shots_range": max(per_club_shots) - min(per_club_shots),
    }, clubs


def bootstrap(sample, rounds=BOOTSTRAP, seed=0):
    """95% interval per metric, resampling matches with replacement."""
    rng = random.Random(seed)
    draws = {}
    for _ in range(rounds):
        resample = [sample[rng.randrange(len(sample))] for _ in sample]
        for k, v in metric_values(resample)[0].items():
            draws.setdefault(k, []).append(v)
    out = {}
    for k, vs in draws.items():
        vs.sort()
        out[k] = (vs[int(0.025 * rounds)], vs[int(0.975 * rounds) - 1])
    return out


SANITY_MATCHES = 100
SANITY_SEED = 70_000


def head_to_head(fixture):
    home, away, seed = fixture
    league = load_league()
    m = simulate_match(league[home], league[away], seed)
    counts = Counter(e.team_id for e in m.events if e.type in PASSES)
    return counts["riverside_athletic"] / (
        counts["riverside_athletic"] + counts["harbour_town"]
    )


def possession_sanity():
    """Riverside (possession, high press) should clearly out-possess Harbour
    (deep 5-4-1). Agent's threshold: mean >= 0.55 and 95% interval above 0.5."""
    pairs = [
        ("riverside_athletic", "harbour_town"),
        ("harbour_town", "riverside_athletic"),
    ]
    games = [(*pairs[i % 2], SANITY_SEED + i) for i in range(SANITY_MATCHES)]
    with ProcessPoolExecutor(mp_context=SPAWN) as pool:
        shares = list(pool.map(head_to_head, games, chunksize=5))
    rng = random.Random(1)
    means = sorted(
        statistics.mean(rng.choice(shares) for _ in shares) for _ in range(BOOTSTRAP)
    )
    lo, hi = means[int(0.025 * BOOTSTRAP)], means[int(0.975 * BOOTSTRAP) - 1]
    mean = statistics.mean(shares)
    return mean, lo, hi, mean >= 0.55 and lo > 0.5


def verdict(ref, lo, hi, value=None):
    if ref["status"] != "ok":
        return "no reference"
    b_lo, b_hi = ref["band"]
    if b_lo <= lo and hi <= b_hi:
        return "PASS"
    if value is not None and b_lo <= value <= b_hi:
        return "FAIL (mean in band; interval crosses the band edge)"
    return "FAIL"


ORDER = [
    "goals_per_match",
    "shots_per_match",
    "team_shots_per_match",
    "team_shots_range",
    "on_target_share",
    "xg_per_shot",
    "ppda",
    "fouls_per_match",
    "corners_per_match",
    "yellow_cards_per_match",
    "red_cards_per_match",
    "pass_completion",
    "passes_per_match",
    "possession_spread",
]


def fmt(v):
    return f"{v:.3f}" if abs(v) < 1 else f"{v:.2f}"


def render(values, intervals, clubs, reference, n, first_seed, holdout, sanity):
    ref = reference["metrics"]
    rows, results = [], {}
    for k in ORDER:
        lo, hi = intervals[k]
        r = ref[k]
        v = verdict(r, lo, hi, values[k])
        results[k] = v
        band = (
            f"{fmt(r['band'][0])} – {fmt(r['band'][1])}" if r["status"] == "ok" else "—"
        )
        if r["status"] == "ok":
            urls = sorted({src["url"].split("/")[2] for src in r["sources"]})
            source = f"{r['publisher']} ({', '.join(urls)}), accessed {r['sources'][0]['accessed']}"
        else:
            source = f"no reference: {r['reason']}"
        rows.append(
            f"| {k} | {fmt(values[k])} ({fmt(lo)} – {fmt(hi)}) | {band} | {source} | **{v}** |"
        )
    passed = sum(v == "PASS" for v in results.values())
    compared = sum(v != "no reference" for v in results.values())
    club_rows = [
        f"| {club} | {c['matches']} | {c['goals'] / c['matches']:.2f} | "
        f"{c['shots'] / c['matches']:.1f} | "
        f"{100 * c['passes'] / (c['passes'] + c['opp_passes']):.1f}% | "
        f"{(c['ppda_passes'] / c['ppda_actions']) if c['ppda_actions'] else float('nan'):.1f} |"
        for club, c in sorted(clubs.items())
    ]
    today = datetime.now(UTC).date().isoformat()
    return f"""# Data realism

Generated by `make realism` (evals/realism/report.py) on {today}. Do not edit by hand.

**{passed} of {compared} compared metrics pass**; {len(ORDER) - compared} have no current
free reference and are shown, not judged.

## How it works

- **Simulated:** {n} free-simulation matches (seeds {first_seed}–{first_seed + n - 1}),
  every ordered pair of the league's clubs in turn, dry weather. Same seeds =
  same numbers.
- **Reference:** season {reference["season"]}, top five European leagues, downloaded
  by `evals/realism/fetch_reference.py` into `evals/realism/reference.yaml`
  (source URL and access date per number). {reference["band_rule"]}.
  No reference number is typed from memory.
- **Pass rule:** the simulated value's 95% interval (bootstrap over matches,
  {BOOTSTRAP} resamples) lies inside the reference band.
- **Tuning:** engine knobs were tuned against these seeds (see DECISIONS.md).
  A hold-out run on seeds never used for tuning guards against over-fitting:
  {holdout}

## Results

| Metric | Simulated (95% interval) | Reference band | Source | Result |
|---|---|---|---|---|
{chr(10).join(rows)}

## Sanity check: possession style

{SANITY_MATCHES} matches Riverside Athletic v Harbour Town (half at each ground):
Riverside's possession (pass share) is **{sanity[0]:.1%}** (95% interval
{sanity[1]:.1%} – {sanity[2]:.1%}). Rule (agent's choice, TUNABLE): at least 55% with
the interval above 50%. **{"PASS" if sanity[3] else "FAIL"}**

## Per club (simulated)

| Club | Matches | Goals for / match | Shots / match | Possession (pass share) | PPDA |
|---|---|---|---|---|---|
{chr(10).join(club_rows)}

## Definitions and known gaps

- **Shots on target** = goals + shots the keeper saves.
- **xG** is the engine's own model (`engine/config/engine.yaml`); the reference is
  Understat's model. Same idea, different models.
- **PPDA** = opponent open-play passes in their own 60% of the pitch, divided by
  tackles, interceptions and fouls in that zone. Understat does not publish its
  exact zone; the standard definition is assumed (see reference.yaml).
- **Possession** (simulated) = share of passes. **Possession spread** = the
  standard deviation of the clubs' average possession.
- **Possession and passing references** come from ESPN's public match
  summaries, an unofficial API (definitions are ESPN's / its data provider's).
  Simulated passes exclude throw-ins.
- Weather is dry in every simulated match; real seasons have mixed weather.
- **Team spread** is compared on 10 fictional clubs against real leagues of
  18-20 teams; with fewer teams the highest-minus-lowest range is naturally a
  little smaller.
"""


def main(argv=None):
    args = argv if argv is not None else sys.argv[1:]

    def arg(name, default):
        return int(args[args.index(name) + 1]) if name in args else default

    n = arg("--matches", MATCHES)
    first_seed = arg("--first-seed", FIRST_SEED)
    reference = yaml.safe_load(REFERENCE.read_text())
    ref = reference["metrics"]

    def run(seed0):
        with ProcessPoolExecutor(mp_context=SPAWN) as pool:
            sample = list(pool.map(summarise, fixtures(n, seed0), chunksize=8))
        values, clubs = metric_values(sample)
        intervals = bootstrap(sample)
        verdicts = {k: verdict(ref[k], *intervals[k], values[k]) for k in ORDER}
        return values, clubs, intervals, verdicts

    values, clubs, intervals, verdicts = run(first_seed)
    for k in ORDER:
        lo, hi = intervals[k]
        print(f"{k:24} {fmt(values[k]):>8} ({fmt(lo)} – {fmt(hi)})  {verdicts[k]}")

    h_values, _, h_intervals, h_verdicts = run(HOLDOUT_FIRST_SEED)
    for k in ORDER:
        lo, hi = h_intervals[k]
        print(
            f"  hold-out {k:24} {fmt(h_values[k]):>8} ({fmt(lo)} – {fmt(hi)})  {h_verdicts[k]}"
        )
    compared = [k for k in ORDER if h_verdicts[k] != "no reference"]
    failing = [k for k in compared if h_verdicts[k] != "PASS"]
    holdout = (
        f"seeds {HOLDOUT_FIRST_SEED}–{HOLDOUT_FIRST_SEED + n - 1}: "
        f"{len(compared) - len(failing)} of {len(compared)} compared metrics pass"
        + (f" (not passing: {', '.join(failing)})." if failing else ".")
    )
    print("hold-out:", holdout)
    sanity = possession_sanity()
    verdict_s = "PASS" if sanity[3] else "FAIL"
    print(
        f"sanity: Riverside v Harbour possession {sanity[0]:.3f} ({sanity[1]:.3f}-{sanity[2]:.3f}) {verdict_s}"
    )
    REPORT.write_text(
        render(values, intervals, clubs, reference, n, first_seed, holdout, sanity)
    )
    print(f"wrote {REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
