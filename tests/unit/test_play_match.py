"""Phase 6: the full match on the physics-first engine (engine/play/match.py).

Short halves keep these quick; the rules are the same as a full 90 minutes
(the full match runs in engine.generate behind ENGINE=physics).
"""

import math

import pytest

from engine.core import teleports
from engine.core.pitch import GOAL_HALF_WIDTH, GOAL_Y, LENGTH, own
from engine.league import load_league
from engine.play.match import FullMatch, simulate_physics_match

HALF = 150.0  # seconds per half in these tests


@pytest.fixture(scope="module")
def league():
    return load_league()


@pytest.fixture(scope="module")
def matches(league):
    return {
        s: simulate_physics_match(
            league["riverside_athletic"], league["harbour_town"], s, half_s=HALF
        )
        for s in (1, 2, 3)
    }


def test_the_match_plays_both_halves_to_the_whistle(matches):
    for seed, r in matches.items():
        periods = {s.period for s in r.tracks.samples}
        assert periods == {1, 2}, seed
        last = r.tracks.samples[-1]
        assert last.period == 2 and last.t >= 2 * HALF, seed
        assert {e.period for e in r.events} == {1, 2}, seed


def test_no_teleports_players_ball_or_referee(matches):
    for seed, r in matches.items():
        assert teleports.find(r.tracks, {e.event_id: e for e in r.events}) == [], seed


def test_events_are_in_order_and_freeze_frames_are_the_track(matches):
    for seed, r in matches.items():
        marks = [r.tracks.events[e.event_id] for e in r.events]
        assert marks == sorted(marks), seed
        clock = [(e.period, e.minute * 60 + e.second) for e in r.events]
        assert clock == sorted(clock), seed
        slot = {pid: k for k, pid in enumerate(r.tracks.slots)}
        for e in r.events:
            s = r.tracks.samples[r.tracks.events[e.event_id]]
            side = 0 if e.team_id == r.match.home_team else 1
            for p in e.freeze_frame:
                x, y = own(side, p.x, p.y)
                assert math.dist((x, y), s.players[slot[p.player_id]][:2]) <= 0.011, (
                    seed,
                    e.type,
                )


def test_every_goal_is_the_ball_over_the_line(matches):
    for seed, r in matches.items():
        for e in r.events:
            if e.type != "shot" or e.outcome != "success":
                continue
            k = r.tracks.events[e.event_id]
            after = r.tracks.samples[k : k + 40]
            gx = LENGTH if e.team_id == r.match.home_team else 0.0
            over = [
                s
                for s in after
                if (s.ball[0] > LENGTH if gx == LENGTH else s.ball[0] < 0.0)
                and abs(s.ball[1] - GOAL_Y) < GOAL_HALF_WIDTH
            ]
            assert over, seed


def test_kick_offs_start_with_everyone_in_his_own_half(league):
    """At each kick-off (start of each half, after each goal) every player
    is in his own half: the restart waited for them."""
    g = FullMatch(league["riverside_athletic"], league["harbour_town"], 2, half_s=HALF)
    seen = []
    orig = g.take_restart

    def take(r):
        if r["kind"] == "kickoff":
            for p in g.players:
                own_half = (
                    p.x <= LENGTH / 2 + 0.5
                    if p.key[0] == 0
                    else p.x >= LENGTH / 2 - 0.5
                )
                assert own_half, (g.t, p.player_id)
            seen.append(g.t)
        orig(r)

    g.take_restart = take
    g.run()
    assert len(seen) >= 2  # both halves at least


def test_the_same_seed_gives_the_same_match(league):
    def dump(r):
        return [e.model_dump_json() for e in r.events], [
            (s.t, s.ball) for s in r.tracks.samples
        ]

    a = simulate_physics_match(
        league["riverside_athletic"], league["harbour_town"], 5, half_s=60.0
    )
    b = simulate_physics_match(
        league["riverside_athletic"], league["harbour_town"], 5, half_s=60.0
    )
    assert dump(a) == dump(b)


def test_the_current_engine_stays_the_default(monkeypatch):
    """ENGINE=physics is opt-in: without it the generator uses engine.core."""
    import engine.generate as gen

    monkeypatch.delenv("ENGINE", raising=False)
    called = []
    monkeypatch.setattr(gen, "physics", lambda *a: called.append(a))
    monkeypatch.setattr(
        gen, "simulate_match", lambda *a, **k: (_ for _ in ()).throw(SystemExit(0))
    )
    with pytest.raises(SystemExit):
        gen.main(["--home", "ashgrove", "--away", "ironvale", "--seed", "1"])
    assert called == []
