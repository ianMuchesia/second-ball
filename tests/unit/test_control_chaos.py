"""Phase 2b: control, openness, scrappiness, xT. Hand-built windows first
(answers worked out in the comments), then the engine-level checks."""

import multiprocessing
import statistics
from concurrent.futures import ProcessPoolExecutor

import pytest

from core.metrics import METRICS, Events, chaos, compute_all, xt
from core.metrics.registry import start_index
from engine.core import simulate_match
from engine.core.sim import load_config, underdog_caution
from engine.league import load_league
from evals.realism.report import fixtures
from tests.unit.test_metrics import A, H, ev

CFG = chaos.config()
# A simple grid for hand calculations: xT = 0.01 per x-cell (x-cell = x // 6.5625).
FLAT = xt.XTGrid(
    values=tuple(tuple(i * 0.01 for _ in range(xt.GRID_Y)) for i in range(xt.GRID_X)),
    version=0,
    trained_on={},
)


@pytest.fixture(autouse=True)
def flat_grid(monkeypatch):
    monkeypatch.setattr(chaos, "grid", lambda: FLAT)


def move(n, t, team, pid, x0, x1, type_="pass", outcome="success", **kw):
    e = ev(n, t, team, type_, pid, outcome=outcome, x=x0, **kw)
    return e.model_copy(update={"end_x": x1})


def events(items, strengths=None):
    return Events.of((H, A), items, strengths)


# Home: pass 40 -> 75 (cells 6 -> 11: +0.05), carry 75 -> 92 (11 -> 14: +0.03),
# shot (xG 0.2). Away wins it with a tackle at 1'00 (p1 ends), passes 30 -> 50
# (cells 4 -> 7: +0.03) and shoots at 1'08 (xG 0.1). Home then has a short
# possession: one failed pass and a bad touch.
WINDOW = [
    move(1, 0, H, "p1", 40, 75),
    move(2, 10, H, "p1", 75, 92, type_="dribble"),
    ev(3, 20, H, "shot", "p1", outcome="fail", x=92, xg=0.2),
    ev(4, 60, A, "tackle", "p1", x=30),
    move(5, 62, A, "p2", 30, 50),
    ev(6, 68, A, "shot", "p2", outcome="fail", x=95, xg=0.1),
    move(7, 90, H, "p3", 50, 60, outcome="fail"),
    ev(8, 92, H, "bad_touch", "p3", outcome="fail", x=60),
]


def val(fn, items=WINDOW, team=None, strengths=None):
    v = fn(events(items, strengths), 0, team)
    return v and round(v.value, 4)


def test_xt_share():
    # Positive xT added: home 0.05 + 0.03 = 0.08, away 0.03 -> home 0.08 / 0.11.
    assert val(chaos.xt_share, team=H) == round(0.08 / 0.11, 4)
    assert chaos.xt_share(events(WINDOW), 0, A).evidence_event_ids == ["e5"]


def test_control_index_is_the_mean_of_its_parts():
    e = events(WINDOW)
    parts = [
        chaos.basic.possession_time(e, 0, H).value,
        chaos.basic.field_tilt(e, 0, H).value,
        chaos.xt_share(e, 0, H).value,
    ]
    assert val(chaos.control_index, team=H) == round(statistics.mean(parts), 4)


def test_two_way_threat_is_the_smaller_xg():
    assert val(chaos.two_way_threat) == 0.1
    one_sided = [e for e in WINDOW if e.event_id != "e6"]
    assert val(chaos.two_way_threat, one_sided) == 0.0


def test_threat_switches():
    # Threat (flat grid: xT > 0.05 from x-cell 6, x >= 39.4): p1 home (the
    # pass ends in cell 11), p2 away (pass ends in cell 7; e5), p3 home (starts
    # in cell 7; e7). Home, away, home = 2 switches.
    assert val(chaos.threat_switches) == 2
    assert chaos.threat_switches(events(WINDOW), 0).evidence_event_ids == ["e5", "e7"]


def test_transition_speed():
    # Away regains with the tackle at 60 s and shoots at 68 s: 8 s. Home wins
    # p3 at 90 s but never reaches a shot or the box, so it is not counted.
    assert val(chaos.transition_speed) == 8
    ids = chaos.transition_speed(events(WINDOW), 0).evidence_event_ids
    assert ids == ["e4", "e6"]


def test_openness_index_by_hand():
    o = CFG["openness"]
    two_way = min(1.0, 0.1 / o["xg_scale"])
    switches = min(1.0, 2 / o["switches_scale"])
    speed = min(1.0, max(0.0, (o["slow_s"] - 8) / (o["slow_s"] - o["fast_s"])))
    w = o["weights"]
    want = (
        w["two_way_threat"] * two_way
        + w["threat_switches"] * switches
        + w["transition_speed"] * speed
    ) / sum(w.values())
    assert val(chaos.openness_index) == round(want, 4)


def test_openness_vs_expected(monkeypatch):
    monkeypatch.setattr(
        chaos,
        "baseline",
        lambda: {
            "buckets": {
                "<0.1": {"mean": 0.2},
                "0.1-0.3": {"mean": 0.3},
                ">0.3": {"mean": 0.1},
            }
        },
    )
    now = val(chaos.openness_index)
    assert val(chaos.openness_vs_expected, strengths=(0.75, 0.45)) == round(
        now - 0.3, 4
    )
    assert val(chaos.openness_vs_expected, strengths=(0.9, 0.4)) == round(now - 0.1, 4)
    assert val(chaos.openness_vs_expected) is None  # no public strengths


def test_scrappiness():
    # Passes per possession: p1 1 (the carry is not a pass), p2 1, p3 1: all
    # three short (< 3 passes).
    assert val(chaos.short_possessions) == 1.0
    # One bad touch in 92 s.
    assert val(chaos.loose_balls) == round(1 / (92 / 60), 4)


def test_language_stays_neutral():
    judging = {"good", "bad", "boring", "exciting", "better", "worse", "poor", "great"}
    for m in METRICS.values():
        words = " ".join([m.definition, *m.display_name.values()]).lower().split()
        assert not judging & set(words), m.name


def test_control_and_openness_reach_match_state():
    out = compute_all(events(WINDOW, (0.6, 0.6)))
    assert "control_index_last_10m" in out[H]
    assert "openness_index_last_10m" in out["match"]
    assert "short_possessions" in out["match"]


def test_xt_value_iteration_by_hand():
    # Cell a (x 100) shoots every time and scores half: xT(a) = 1 * 0.5.
    # Cell b (x 60) only passes: half to a, half fail: xT(b) = 1 * 0.5 * 0.5.
    shots = [
        ev(i, i, H, "shot", "p", outcome="success" if i % 2 else "fail", x=100)
        for i in range(4)
    ]
    passes = [
        move(10, 10, H, "p", 60, 100),
        move(11, 11, H, "p", 60, 100, outcome="fail"),
    ]
    values, _ = xt.fit([shots + passes])
    grid = xt.XTGrid(values=values, version=0, trained_on={})
    assert grid.at(100, 34) == pytest.approx(0.5)
    assert grid.at(60, 34) == pytest.approx(0.25)


def test_saved_xt_artifact_is_versioned_and_from_free_play():
    g = xt.load(CFG["xt_version"])
    assert g.version == CFG["xt_version"]
    assert g.trained_on["mode"] == "free_simulation"
    assert g.trained_on["matches"] >= 500
    # Threat rises towards the opponent's goal.
    assert g.at(100, 34) > g.at(60, 34) > g.at(10, 34)


# ---- engine-level ----------------------------------------------------------------


def test_underdog_caution_scales_with_the_gap():
    cfg = load_config()
    assert underdog_caution(cfg, 0.9, 0.4) == 0.0
    assert underdog_caution(cfg, 0.6, 0.6) == 0.0
    assert 0 < underdog_caution(cfg, 0.5, 0.7) < underdog_caution(cfg, 0.4, 0.9) == 1.0


def mean_openness(fixture):
    home, away, seed = fixture
    league = load_league()
    m = simulate_match(league[home], league[away], seed)
    e = Events.for_match(m.match)
    values, nxt = [], 600
    for event in m.events:
        e.append(event)
        if e.now() >= nxt:
            v = chaos.openness_index(e, start_index(e, 10))
            if v is not None:
                values.append(v.value)
            nxt += 60
    gap = abs(m.match.home_strength - m.match.away_strength)
    return gap, statistics.mean(values)


# These two need a full season to show (they fail on 50 matches for want of
# close games, mismatches and late chasing spells): nightly, make test-slow.
@pytest.mark.slow
def test_openness_is_lower_in_mismatches(monkeypatch, n=300):
    monkeypatch.setattr(chaos, "grid", lambda: xt.load(CFG["xt_version"]))
    with ProcessPoolExecutor(mp_context=multiprocessing.get_context("spawn")) as pool:
        results = list(pool.map(mean_openness, fixtures(n, 90_000), chunksize=8))
    close = [o for gap, o in results if gap < 0.1]
    mismatch = [o for gap, o in results if gap > 0.3]
    assert len(close) >= 30 and len(mismatch) >= 30
    assert statistics.mean(mismatch) < statistics.mean(close)


def chasing_spells(fixture):
    """Per match: mean two-way threat of 10-minute windows (one per minute) in
    late chasing spells (margin 1, minute >= 75, the trailing team in chase
    mode) and in the same match's 0-30' windows."""
    home, away, seed = fixture
    league = load_league()
    m = simulate_match(league[home], league[away], seed)
    switches = sorted(m.mode_log, key=lambda s: s["events"])
    mode = {home: "normal", away: "normal"}
    goals = {home: 0, away: 0}
    e = Events.for_match(m.match)
    late, early, k, nxt = [], [], 0, 60
    for i, event in enumerate(m.events):
        while k < len(switches) and switches[k]["events"] <= i:
            mode[switches[k]["team"]] = switches[k]["mode"]
            k += 1
        e.append(event)
        if event.outcome == "owngoal":
            goals[e.opponent(event.team_id)] += 1
        elif event.type.startswith("shot") and event.outcome == "success":
            goals[event.team_id] += 1
        if e.now() < nxt:
            continue
        nxt += 60
        v = chaos.two_way_threat(e, start_index(e, 10))
        if v is None:
            continue
        if event.period == 1 and event.minute <= 30:
            early.append(v.value)
        trailing = min(goals, key=goals.get)
        if (
            event.minute >= 75
            and abs(goals[home] - goals[away]) == 1
            and mode[trailing] == "chase"
        ):
            late.append(v.value)
    if not late or not early:
        return None
    return statistics.mean(late) - statistics.mean(early)


@pytest.mark.slow
def test_late_chasing_spells_are_more_two_way_than_the_first_half_hour(n=300):
    # Ian (2026-10-22): the general rule, over free matches, instead of one demo.
    with ProcessPoolExecutor(mp_context=multiprocessing.get_context("spawn")) as pool:
        diffs = [
            d
            for d in pool.map(chasing_spells, fixtures(n, 91_000), chunksize=8)
            if d is not None
        ]
    mean = statistics.mean(diffs)
    half = 1.96 * statistics.stdev(diffs) / len(diffs) ** 0.5
    print(
        f"late chasing - early two-way threat: {mean:+.3f} xG "
        f"(95% CI {mean - half:+.3f} to {mean + half:+.3f}, n={len(diffs)} matches)"
    )
    assert len(diffs) >= 50
    assert mean > 0


def test_weaker_teams_lose_more_passes_under_pressure():
    league = load_league()
    rates = {}
    for club, opp in (("westmarch", "saltmere"), ("ironvale", "saltmere")):
        ok = total = 0
        for seed in range(6):
            m = simulate_match(league[club], league[opp], 95_000 + seed)
            for e in m.events:
                if e.team_id == club and e.type == "pass" and e.under_pressure:
                    total += 1
                    ok += e.outcome == "success"
        rates[club] = ok / total
    assert rates["ironvale"] < rates["westmarch"]
