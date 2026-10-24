"""Moment detector: hand-built cases, then the scripted demo's known facts."""

import pytest

from core.metrics import Events
from core.moments import KINDS, MomentDetector, config, detect
from engine.core import simulate_match
from engine.league import load_league
from engine.scenarios import load_scenario
from tests.unit.test_phase2c import A, H, event, opp


def run(items):
    det, walk, out = MomentDetector(), Events(teams=(H, A)), []
    for e in items:
        walk.append(e)
        out += det.update(walk)
    return out


def test_goal_is_a_moment_with_evidence():
    goal = event(1, 10, H, "shot", "success", at=(95, 34), pid="p1", xg=0.4)
    (m,) = [m for m in run([goal]) if m.kind == "goal"]
    assert (m.team, m.importance, m.evidence_event_ids) == (H, 1.0, ["e1"])
    # The goal's own chance, as its own number: never a circular "xG after".
    assert m.metrics_after["shot_xg"].value == 0.4
    assert "xg" not in m.metrics_after


def test_big_chance_threshold_and_cooldown():
    # Non-goal shots with xG >= 0.3; the same kind + team at most once per 3 min.
    shots = [
        event(1, 0, H, "shot", "fail", at=(95, 34), pid="p1", xg=0.35),
        event(2, 60, H, "shot", "fail", at=(95, 34), pid="p2", xg=0.5),  # cooldown
        event(3, 120, H, "shot", "fail", at=(95, 34), pid="p3", xg=0.2),  # too small
        event(4, 200, H, "shot", "fail", at=(95, 34), pid="p4", xg=0.31),  # 200 s later
    ]
    big = [m for m in run(shots) if m.kind == "big_chance"]
    assert [m.evidence_event_ids for m in big] == [["e1"], ["e4"]]


def test_bad_situation_moment():
    # Own box, facing own goal, an opponent 1 m away (Ian's rule).
    trouble = event(1, 0, H, "pass", at=(10, 34), facing=180, others=[opp(1, 9, 34)])
    (m,) = [m for m in run([trouble]) if m.kind == "bad_situation"]
    assert m.team == H and m.importance == config()["importance"]["bad_situation"]
    assert set(m.metrics_after) == {"risk", "pressure", "options"}


def counter(n, t, pid_lost, pid_won):
    """Away has the ball, home tackles in its own half (x 40), then a 22 m
    pass into the right-hand channel (y 10: the defenders' LEFT), ending behind
    the away defender nearest that touchline (x 55)."""
    return [
        event(n, t, A, "pass", at=(60, 34), to=(65, 34), pid=pid_lost),
        event(n + 1, t + 1, H, "tackle", at=(40, 34), pid=pid_lost),
        event(
            n + 2,
            t + 3,
            H,
            "pass",
            at=(40, 30),
            to=(62, 10),
            pid=pid_won,
            others=[opp(1, 55, 6), opp(2, 80, 34), opp(3, 104, 34)],
        ),
    ]


def test_second_counter_behind_the_same_full_back_is_a_pattern():
    items = counter(1, 0, "p1", "p2") + counter(4, 400, "p3", "p4")
    (m,) = [m for m in run(items) if m.kind == "repeated_pattern"]
    assert m.team == H
    assert m.metrics_after["counters_behind_left_back"].value == 2
    assert m.evidence_event_ids == ["e5", "e6"]  # the regain and the long ball


def test_edge_fires_once_while_a_condition_lasts():
    det = MomentDetector()
    assert [det.edge("pressure_spike", H, x) for x in (True, True, False, True)] == [
        True,
        False,
        False,
        True,
    ]


@pytest.fixture(scope="module")
def demo():
    sc = load_scenario("demo_riverside_harbour")
    league = load_league()
    m = simulate_match(
        league[sc.home], league[sc.away], sc.seed, weather=sc.weather, scenario=sc
    )
    return m, detect(Events.for_match(m.match, m.events))


def test_demo_goals_and_red_card_impact(demo):
    _, moments = demo
    goals = [(x.team, x.clock.minute) for x in moments if x.kind == "goal"]
    assert goals == [("harbour_town", 34), ("harbour_town", 88)]
    (red,) = [x for x in moments if x.kind == "red_card_impact"]
    assert red.team == "riverside_athletic" and 63 <= red.clock.minute <= 64
    # Before and after numbers for the same metrics.
    assert set(red.metrics_before) == set(red.metrics_after) >= {"control_index"}


def test_every_moment_is_well_formed(demo):
    _, moments = demo
    imp = config()["importance"]
    for x in moments:
        assert x.kind in KINDS
        assert x.importance == imp[x.kind]
        assert x.evidence_event_ids
    assert len({x.moment_id for x in moments}) == len(moments)


def test_detector_is_deterministic(demo):
    m, moments = demo
    again = detect(Events.for_match(m.match, m.events))
    assert [x.model_dump() for x in again] == [x.model_dump() for x in moments]


def test_not_spamming_free_matches():
    league = load_league()
    per_minute = []
    for k, (home, away) in enumerate(
        [
            ("saltmere", "tidewick"),
            ("ironvale", "westmarch"),
            ("ashgrove", "kilele_chui"),
        ]
    ):
        m = simulate_match(league[home], league[away], 61_000 + k)
        moments = detect(Events.for_match(m.match, m.events))
        per_minute.append(len(moments) / (m.events[-1].minute + 1))
    # docs/EVAL.md reports the full 50-match check; here: well under one a minute.
    assert max(per_minute) < 1.0
