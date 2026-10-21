"""Set pieces (Ian, 2026-10-22): club threat, foul drawing, corners, late leaders."""

import collections
import multiprocessing
from concurrent.futures import ProcessPoolExecutor

import pytest

from engine.core import simulate_match
from engine.league import load_league
from evals.realism.report import fixtures

LEAGUE = load_league()
SET_PIECE_DELIVERY = {"corner_crossed", "freekick_crossed"}


def tally(fixture):
    home, away, seed = fixture
    league = load_league()
    m = simulate_match(league[home], league[away], seed)
    c = collections.Counter()
    goals = {home: 0, away: 0}
    for e in m.events:
        team, other = e.team_id, (away if e.team_id == home else home)
        c[(team, "matches")] += 0
        if e.type == "corner_crossed":
            c[(team, "corners")] += 1
        # Challenges on `other` in its final third (= the defender's own third).
        if e.type in ("foul", "tackle") and e.start_x < 105 / 3:
            c[(other, "challenges_high")] += 1
            c[(other, "fouls_won_high")] += e.type == "foul"
        if e.type.startswith("shot") and e.qualifiers.get("assist") == "set_piece":
            c[(team, "sp_xg")] += e.qualifiers["xg"]
        if e.type.startswith("freekick") and e.start_x > 70 and e.minute >= 85:
            lead = goals[team] - goals[other]
            if lead > 0:
                c[("late_leader_fk", e.type)] += 1
        if e.type.startswith("shot") and e.outcome == "success":
            goals[team] += 1
    c[(home, "matches")] += 1
    c[(away, "matches")] += 1
    return c


@pytest.fixture(scope="module")
def season():
    with ProcessPoolExecutor(mp_context=multiprocessing.get_context("spawn")) as pool:
        return sum(
            pool.map(tally, fixtures(312, 40_000), chunksize=8), collections.Counter()
        )


def per_match(season, club, key):
    return season[(club, key)] / season[(club, "matches")]


def league_average(season, key, exclude=()):
    clubs = [c for c in LEAGUE if c not in exclude]
    return sum(per_match(season, c, key) for c in clubs) / len(clubs)


def test_set_piece_threat_order(season):
    xg = {c: per_match(season, c, "sp_xg") for c in LEAGUE}
    assert (
        xg["thornfield_athletic"]
        > xg["kingsbridge_ravens"]
        > league_average(season, "sp_xg")
    )
    assert xg["thornfield_athletic"] == max(xg.values())


def foul_rate(season, club):
    return season[(club, "fouls_won_high")] / season[(club, "challenges_high")]


def test_foul_drawing_clubs_win_more_fouls_per_challenge(season):
    others = [c for c in LEAGUE if c not in ("port_ilvane", "tidewick")]
    average = sum(foul_rate(season, c) for c in others) / len(others)
    for club in ("port_ilvane", "tidewick"):
        assert foul_rate(season, club) > average * 1.2


def test_late_leaders_put_final_third_free_kicks_into_the_box(season):
    crossed = season[("late_leader_fk", "freekick_crossed")]
    short = season[("late_leader_fk", "freekick_short")]
    assert crossed > 0
    assert short == 0


def test_set_piece_knobs_default_for_other_clubs():
    sp = LEAGUE["ashgrove"].set_pieces
    assert (sp.threat, sp.foul_drawing, sp.corner_seeking) == (0.5, 0.3, 0.3)
