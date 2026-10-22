"""Ian's game-state rules (2026-10-21): manage / protect / chase, hysteresis."""

import collections
import multiprocessing
from concurrent.futures import ProcessPoolExecutor

import pytest

from engine.core import simulate_match
from engine.core.shape import TeamState
from engine.core.sim import load_config
from engine.league import load_league
from evals.realism.report import fixtures

LEAGUE = load_league()
CFG = load_config()["game_state"]
PASSES = {"pass", "cross", "throw_in", "goalkick", "freekick_short", "corner_crossed"}


def play(fixture):
    home, away, seed = fixture
    league = load_league()
    m = simulate_match(league[home], league[away], seed)
    goals = {home: 0, away: 0}
    passes = collections.Counter()  # (team, bucket, own|opp)
    leads = []  # (event index, team, lead) after each goal
    for i, e in enumerate(m.events):
        for team, opp in ((home, away), (away, home)):
            lead = goals[team] - goals[opp]
            if e.minute < CFG["from_minute"]:
                bucket = "before"
            elif lead == 1:
                bucket = "lead1"
            elif lead >= CFG["comfortable_margin"]:
                bucket = "lead4"
            else:
                continue
            if e.type in PASSES:
                passes[(team, bucket, "own" if e.team_id == team else "opp")] += 1
        if e.type.startswith("shot") and e.outcome == "success":
            goals[e.team_id] += 1
            # Event order, not the clock: event times are whole seconds, so a
            # switch and a goal in the same second would look simultaneous.
            leads.append((i, home, goals[home] - goals[away]))
            leads.append((i, away, goals[away] - goals[home]))
    return passes, m.mode_log, leads


STRONG = [
    "westmarch",
    "thornfield_athletic",
    "riverside_athletic",
    "kingsbridge_ravens",
]
WEAK = ["ironvale", "port_ilvane", "harbour_town"]


def mismatches(n, first_seed=60_000):
    """Strong v weak fixtures, where 4-goal leads actually happen."""
    pairs = [(s, w) for s in STRONG for w in WEAK] + [
        (w, s) for s in STRONG for w in WEAK
    ]
    return [(*pairs[i % len(pairs)], first_seed + i) for i in range(n)]


@pytest.fixture(scope="module")
def mismatch_season():
    with ProcessPoolExecutor(mp_context=multiprocessing.get_context("spawn")) as pool:
        return list(pool.map(play, mismatches(200), chunksize=8))


@pytest.fixture(scope="module")
def season():
    with ProcessPoolExecutor(mp_context=multiprocessing.get_context("spawn")) as pool:
        return list(pool.map(play, fixtures(200, 20_000), chunksize=8))


def share(passes, team, bucket):
    own, opp = passes[(team, bucket, "own")], passes[(team, bucket, "opp")]
    return own / (own + opp) if own + opp >= 20 else None


def possession_drop(season, bucket):
    drops = []
    for passes, _, _ in season:
        for team in {k[0] for k in passes}:
            before, after = share(passes, team, "before"), share(passes, team, bucket)
            if before is not None and after is not None:
                drops.append(before - after)
    return sum(drops) / len(drops), len(drops)


def test_one_goal_leaders_have_less_possession_after_65(season):
    drop, n = possession_drop(season, "lead1")
    assert n >= 50
    assert drop >= 0.02  # at least 2 points of possession given up


def test_four_goal_leaders_change_less_than_one_goal_leaders(mismatch_season):
    # Both groups from the same strong-v-weak matches (with 13 clubs, 4-goal
    # leads are too rare in a general sample of 200 to compare).
    drop1, n1 = possession_drop(mismatch_season, "lead1")
    drop4, n4 = possession_drop(mismatch_season, "lead4")
    assert n1 >= 20 and n4 >= 20
    assert drop4 < drop1


def test_four_goal_leaders_never_manage_or_protect(season):
    for _, mode_log, leads in season:
        for switch in mode_log:
            if switch["mode"] not in ("manage", "protect"):
                continue
            before = [
                lead
                for i, team, lead in leads
                if i < switch["events"] and team == switch["team"]
            ]
            assert not before or before[-1] < CFG["comfortable_margin"]


def test_threat_switches_at_most_once_per_5_minutes(season):
    for _, mode_log, _ in season:
        last = {}
        for switch in mode_log:
            if switch["reason"] in ("threat", "calm") and switch["team"] in last:
                assert switch["t"] - last[switch["team"]] >= CFG["min_mode_s"]
            last[switch["team"]] = switch["t"]


def test_protect_happens_and_calms_down(season):
    reasons = collections.Counter(s["reason"] for _, log, _ in season for s in log)
    assert reasons["threat"] > 0 and reasons["calm"] > 0


def test_red_card_shape_from_club_yaml():
    team = TeamState.start(0, LEAGUE["riverside_athletic"])
    lcb = next(p for p, r in team.roles.items() if r == "LCB")
    team.send_off(lcb)
    assert team.red_table is not None
    back = {
        r for r, (d, _) in team.shape("out_of_possession", "centre").items() if d == 0
    }
    assert back == {"RB", "RCB", "LCB", "LB"}  # 4-4-1: the back four stays


def test_clubs_without_red_card_shape_drop_a_forward():
    team = TeamState.start(0, LEAGUE["ironvale"])
    team.send_off(2)
    assert team.red_table is None and len(team.roles) == 9


def test_protect_shape_is_a_back_five_for_riverside():
    team = TeamState.start(0, LEAGUE["riverside_athletic"])
    team.mode = "protect"
    back = [
        r for r, (d, _) in team.shape("out_of_possession", "centre").items() if d == 0
    ]
    assert sorted(back) == ["DM", "LB", "LCB", "RB", "RCB"]
    team.mode = "manage"
    assert (
        team.shape("out_of_possession", "centre")
        == team.table[("out_of_possession", "centre")]
    )
