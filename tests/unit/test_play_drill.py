"""Stage 1 of the physics-first engine: the drill pitch (engine/play).

One attacker, one defender, one keeper and a loose ball. Nobody is told who
wins it. These tests hold the physics to its assumptions (docs/PHYSICS.md
gives each tolerance and why), and the drill to the rules Ian set: no
teleports, possession only by reaching and controlling the ball, events and
tracks that agree, the same seed giving the same drill.
"""

import itertools
import json
import math

import pytest

from engine.core import teleports
from engine.core.pitch import LENGTH, WIDTH, own
from engine.league import load_league
from engine.play.ball import Ball, predict
from engine.play.drill import Drill, load_play, run_drill
from engine.play.player import Player, intercept, run_time

CFG = load_play()
BALL, PL, CONTROL = CFG["ball"], CFG["player"], CFG["control"]
SEEDS = range(1, 101)


@pytest.fixture(scope="module")
def league():
    return load_league()


@pytest.fixture(scope="module")
def drills(league):
    return {
        s: run_drill(league["riverside_athletic"], league["harbour_town"], s)
        for s in SEEDS
    }


# ---- the ball -------------------------------------------------------------------


def roll(v0):
    b = Ball(50.0, 34.0)
    b.kick(v0, 0.0)
    speeds, t = [], 0.0
    while b.moving and t < 60:
        b.step(CFG["dt"], BALL, CFG["substeps"])
        t += CFG["dt"]
        speeds.append(b.ground_speed)
    return b, speeds, t


@pytest.mark.parametrize("v0", [4.0, 8.0, 15.0])
def test_a_rolling_ball_slows_steadily_and_stops_short_of_friction_alone(v0):
    b, speeds, t = roll(v0)
    assert not b.moving and t < 60
    assert all(b2 <= b1 + 1e-9 for b1, b2 in itertools.pairwise(speeds))
    friction_only = v0**2 / (2 * BALL["roll_decel"])
    travelled = b.x - 50.0
    # Air drag only shortens the roll; a slow ball loses little to it.
    assert travelled <= friction_only + 0.2
    if v0 <= 4.0:
        assert travelled >= 0.9 * friction_only


def test_a_lofted_ball_lands_and_bounces_lower_each_time():
    b = Ball(30.0, 34.0)
    b.kick(15.0, 0.0, lift=10.0)
    peaks, h_prev, rising, t = [], 0.0, True, 0.0
    while b.moving and t < 30:
        b.step(CFG["dt"], BALL, CFG["substeps"])
        t += CFG["dt"]
        assert b.h >= 0.0 and not math.isnan(b.x + b.y + b.h)
        if rising and b.h < h_prev:
            peaks.append(h_prev)
        rising = b.h >= h_prev
        h_prev = b.h
    assert len(peaks) >= 2
    assert all(p2 < p1 for p1, p2 in itertools.pairwise(peaks))
    # Without drag a 10 m/s rise peaks at 5.1 m; drag takes a little off.
    assert 4.0 < peaks[0] < 5.1


def test_predicting_the_ball_does_not_move_it_and_matches_the_real_path():
    b = Ball(40.0, 30.0)
    b.kick(9.0, 20.0)
    before = (b.x, b.y, b.vx, b.vy)
    path = predict(b, BALL, 3.0, CFG["dt"], CFG["substeps"])
    assert (b.x, b.y, b.vx, b.vy) == before
    for tau, x, y, _ in path[1:6]:
        b.step(CFG["dt"], BALL, CFG["substeps"])
        assert math.isclose(b.x, x, abs_tol=1e-9) and math.isclose(b.y, y, abs_tol=1e-9)


# ---- reaching it -----------------------------------------------------------------


def test_run_time_from_standing_follows_constant_acceleration():
    # 10 m from rest at 3.5 m/s^2 (top speed not reached until 10.3 m).
    assert math.isclose(
        run_time(10.0, 0.0, 8.5, 3.5), math.sqrt(20 / 3.5), rel_tol=1e-6
    )
    # Already at top speed: distance over speed.
    assert math.isclose(run_time(17.0, 8.5, 8.5, 3.5), 2.0, rel_tol=1e-6)


def test_a_simulated_run_takes_about_the_estimated_time():
    """The reach estimate the players decide with agrees with how their
    bodies actually move (tolerance: docs/PHYSICS.md, 0.4 s)."""
    for d in (5.0, 15.0, 30.0):
        pl = Player((0, 1), "a", "h", False, 20.0, 34.0)
        est = run_time(d - CONTROL["feet_m"], 0.0, PL["top_speed"], PL["accel"])
        t = 0.0
        while math.dist(pl.pos, (20.0 + d, 34.0)) > CONTROL["feet_m"] and t < 20:
            pl.move((20.0 + d, 34.0), PL["top_speed"], CFG["dt"], PL, arrive_in=0.0)
            t += CFG["dt"]
        assert abs(t - est) <= 0.4, (d, t, est)


def test_the_first_reachable_point_not_the_nearest_one():
    """A player beside a fast ball cannot have it where it is now; he gets
    it further along, where he can be first."""
    b = Ball(30.0, 34.0)
    b.kick(12.0, 0.0)
    path = predict(b, BALL, 5.0, CFG["dt"], CFG["substeps"])
    pl = Player((1, 4), "d", "a", False, 32.0, 40.0)
    tau, point = intercept(
        pl, path, 0.0, CONTROL["feet_m"], CONTROL["feet_height_m"], PL
    )
    assert tau > 0.5 and point[0] > 36.0
    # ...and the answer is consistent: at that time the ball is at that point.
    at = min(path, key=lambda p: abs(p[0] - tau))
    assert math.dist(point, at[1:3]) < 1e-6


# ---- the drill -------------------------------------------------------------------


def as_json(result):
    return json.dumps(
        {
            "events": [e.model_dump(mode="json") for e in result.events],
            "samples": [
                [s.t, s.ball, s.players, s.dead] for s in result.tracks.samples
            ],
            "marks": result.tracks.events,
            "outcome": result.outcome,
        },
        sort_keys=True,
    )


def test_the_same_seed_gives_the_same_drill_byte_for_byte(league):
    a = run_drill(league["riverside_athletic"], league["harbour_town"], 7)
    b = run_drill(league["riverside_athletic"], league["harbour_town"], 7)
    c = run_drill(league["riverside_athletic"], league["harbour_town"], 8)
    assert as_json(a) == as_json(b)
    assert as_json(a) != as_json(c)


def test_no_teleports_and_no_impossible_speeds(drills):
    top = PL["top_speed"] + PL["push_m"] / CFG["dt"]  # a body push on a sprint
    for seed, r in drills.items():
        assert teleports.find(r.tracks, {e.event_id: e for e in r.events}) == [], seed
        s = r.tracks.samples
        for a, b in itertools.pairwise(s):
            for p, q in zip(a.players, b.players, strict=True):
                if p and q:
                    assert math.dist(p[:2], q[:2]) / CFG["dt"] <= top + 1e-6, seed


def test_the_ball_is_always_somewhere_real(drills):
    for seed, r in drills.items():
        for s in r.tracks.samples:
            x, y, h = s.ball
            assert not any(math.isnan(v) for v in (x, y, h)), seed
            assert h >= 0.0
            assert s.dead or (-0.2 <= x <= LENGTH + 0.2 and -0.2 <= y <= WIDTH + 0.2)


def test_all_three_outcomes_come_out_of_play_not_a_script(drills):
    outcomes = {r.outcome for r in drills.values()}
    assert {"attacker_kept", "defender_won", "keeper_claimed"} <= outcomes


def test_a_keeper_only_holds_the_ball_inside_his_area(drills):
    """Hands outside the area is a handball: he claims it only if he will
    stop inside it (a sprinting keeper goes down on it and slides)."""
    from engine.play.drill import BOX_DEPTH, BOX_HALF

    for seed, r in drills.items():
        for e in r.events:
            if e.type != "keeper_pick_up":
                continue
            slot = r.tracks.slots.index(e.player_id)
            for s in r.tracks.samples[r.tracks.events[e.event_id] :]:
                x, y, _ = s.players[slot]
                assert x >= LENGTH - BOX_DEPTH and abs(y - WIDTH / 2) <= BOX_HALF, seed


def test_possession_changes_only_where_the_winner_reached_the_ball(drills):
    """At the sample an interception or pick-up is written, the ball was
    within that player's reach (feet, or a keeper's hands in his area)."""
    for seed, r in drills.items():
        slot = {pid: k for k, pid in enumerate(r.tracks.slots)}
        for e in r.events:
            if e.type == "bad_touch":
                continue
            s = r.tracks.samples[r.tracks.events[e.event_id]]
            p = s.players[slot[e.player_id]]
            reach = (
                CONTROL["keeper_hands_m"]
                if e.type == "keeper_pick_up"
                else CONTROL["feet_m"]
            )
            # The ball is now at his feet / in his hands (carried this step).
            assert (
                math.dist(p[:2], s.ball[:2]) <= max(reach, BALL["carry_ahead"]) + 1e-6
            ), seed
            assert e.second == int(s.t % 60), seed


def test_events_and_tracks_agree(drills):
    """Every event's freeze frame IS the track at its sample (to the cm), and
    the ball is where the event says it starts."""
    for seed, r in drills.items():
        slot = {pid: k for k, pid in enumerate(r.tracks.slots)}
        for e in r.events:
            s = r.tracks.samples[r.tracks.events[e.event_id]]
            side = 0 if e.team_id == r.match.home_team else 1
            for p in e.freeze_frame:
                x, y = own(side, p.x, p.y)
                q = s.players[slot[p.player_id]]
                assert math.dist((x, y), q[:2]) <= 0.011, (seed, e.type)
            bx, by = own(side, e.start_x, e.start_y)
            assert math.dist((bx, by), s.ball[:2]) <= 0.011, (seed, e.type)


def test_nobody_runs_alongside_a_loose_ball_without_playing_it(drills):
    """A chaser within 2 m of a loose, low ball for 1.5 s and not taking it
    is the bug Ian saw ('someone near the ball ignores it')."""
    for seed, r in drills.items():
        s = r.tracks.samples
        touch = r.tracks.events[r.events[0].event_id]
        won = len(s) if r.won_sample is None else r.won_sample
        for k in range(len(r.tracks.slots)):
            near = 0
            for i in range(touch + 3, won):
                p = s[i].players[k]
                close = (
                    p is not None
                    and s[i].ball[2] < 1.0
                    and math.dist(p[:2], s[i].ball[:2]) < 2.0
                )
                near = near + 1 if close else 0
                assert near <= 15, (seed, r.tracks.slots[k])


def test_a_drill_is_a_run_the_screen_can_open(league, tmp_path, monkeypatch):
    from engine.play.__main__ import write_run
    from stream.api import load

    r = run_drill(league["riverside_athletic"], league["harbour_town"], 3)
    write_run(r, tmp_path / "drill-3", "drill-3")
    monkeypatch.setenv("RUNS_DIR", str(tmp_path))
    b = load("drill-3")
    assert [e.event_id for e in b["events"]] == [e.event_id for e in r.events]
    assert (tmp_path / "drill-3" / "tracks.bin").stat().st_size > 0
    assert json.loads((tmp_path / "drill-3" / "tracks.json").read_text())["n"] == len(
        r.tracks.samples
    )


def test_the_drill_leaves_the_current_engine_alone():
    """Stage 1 is behind its own entry point: the default engine is unchanged."""
    from engine.core import sim

    assert not hasattr(sim, "Drill")
    assert Drill.__module__ == "engine.play.drill"
