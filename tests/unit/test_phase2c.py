"""Phase 2c metrics on hand-built frames and windows; every answer is worked
out by hand in the comments. SPADL frame: the acting team attacks towards
x = 105; the defending team's own goal is at x = 105."""

import math

import pytest

from core.contracts import MatchEvent, PlayerPosition
from core.metrics import METRICS, Events, chaos, compute_all, play, positional, xt
from core.metrics.registry import EVENT_KEY
from scripts.export_metrics_doc import render

H, A = "home", "away"
FLAT = xt.XTGrid(
    values=tuple(tuple(i * 0.01 for _ in range(xt.GRID_Y)) for i in range(xt.GRID_X)),
    version=0,
    trained_on={},
)


@pytest.fixture(autouse=True)
def flat_grid(monkeypatch):
    monkeypatch.setattr(chaos, "grid", lambda: FLAT)
    monkeypatch.setattr(play, "grid", lambda: FLAT)


def p(pid, team, x, y, facing=0.0):
    return PlayerPosition(player_id=pid, team_id=team, x=x, y=y, facing_deg=facing)


def event(
    n,
    t=0,
    team=H,
    type_="pass",
    outcome="success",
    at=(50.0, 34.0),
    to=None,
    facing=0.0,
    others=(),
    pid="pos",
    under_pressure=False,
    speed=None,
    **qual,
):
    minute, second = divmod(t, 60)
    to = to or at
    frame = [p(f"{team}-9", team, *at, facing), *others]
    return MatchEvent(
        event_id=f"e{n}",
        match_id="m",
        possession_id=pid,
        period=1,
        minute=minute,
        second=second,
        team_id=team,
        player_id=f"{team}-9",
        type=type_,
        outcome=outcome,
        body_part="foot",
        start_x=at[0],
        start_y=at[1],
        end_x=to[0],
        end_y=to[1],
        under_pressure=under_pressure,
        ball_speed_kmh=speed,
        qualifiers=qual,
        freeze_frame=frame,
    )


def at0(e, fn):
    return round(fn(Events.of((H, A), [e]), 0).value, 4)


def opp(k, x, y):
    return p(f"{A}-{k}", A, x, y)


def mate(k, x, y):
    return p(f"{H}-{k}", H, x, y)


# ---- pressure (Ian: 1 within 2 m, straight line to 0.2 at 5 m, x2 in front or
# goal-side, one close opponent = 0.5) ------------------------------------------------


def test_pressure_by_hand():
    behind = event(1, others=[opp(1, 48.5, 34)])  # 1.5 m behind: weight 1 -> 0.5
    assert at0(behind, positional.pressure) == 0.5
    in_front = event(1, others=[opp(1, 51.5, 34)])  # in front AND goal-side: x2 once
    assert at0(in_front, positional.pressure) == 1.0
    # 3.5 m behind: 0.2 + 0.8 * (5 - 3.5) / 3 = 0.6 -> 0.6 / 2 = 0.3
    assert at0(event(1, others=[opp(1, 46.5, 34)]), positional.pressure) == 0.3
    assert at0(event(1, others=[opp(1, 44, 34)]), positional.pressure) == 0.0


def test_in_front_follows_where_he_faces():
    # Facing his own goal (180): an opponent at smaller x is in front of him.
    # 1.5 m away, in front (not goal-side): weight 1 x2 -> 1.0.
    e = event(1, facing=180, others=[opp(1, 48.5, 34)])
    assert at0(e, positional.pressure) == 1.0


def test_facing_own_goal():
    assert at0(event(1, facing=180), positional.facing_own_goal) == 1
    assert at0(event(1, facing=100), positional.facing_own_goal) == 0


# ---- options --------------------------------------------------------------------


def test_options_by_hand():
    others = [
        mate(2, 60, 34),  # lane blocked: opponent 1 m off it
        opp(1, 55, 35),
        mate(3, 50, 50),  # clear lane
        mate(4, 90, 40),  # clearly offside: second-last defender at x 80
        opp(2, 80, 60),
        opp(3, 100, 34),  # their keeper (last man)
        mate(5, 80.5, 10),  # 0.5 m beyond: not clearly offside, lane clear
    ]
    assert at0(event(1, others=others), positional.options) == 2


# ---- risk and bad situation -------------------------------------------------------


def test_risk_falls_smoothly_from_own_goal():
    assert at0(event(1, at=(5, 34)), positional.risk) == round(
        math.exp(-((5 / 40) ** 2)), 4
    )
    half = at0(event(1, at=(52.5, 34), others=[opp(1, 60, 34)]), positional.risk)
    assert half == round(math.exp(-((52.5 / 40) ** 2)), 4)
    # Box corner (16.5, 13.84): about 0.66, above the 0.6 bad-situation line.
    assert at0(event(1, at=(16.5, 13.84)), positional.risk) > 0.6


def test_risk_is_about_zero_with_no_defender_left():
    # Final third, the only outfield defender is behind the ball.
    e = event(1, at=(80, 34), others=[opp(1, 75, 34), opp(2, 104, 34)])
    assert at0(e, positional.risk) == 0.0


def test_bad_situation_by_hand():
    # Own box, facing own goal, an opponent 1 m away: risk ~0.94, pressure 1.0.
    trouble = event(1, at=(10, 34), facing=180, others=[opp(1, 9, 34)])
    assert at0(trouble, positional.bad_situation) == 1
    # Same, but facing upfield: not a bad situation.
    calm = event(1, at=(10, 34), facing=0, others=[opp(1, 9, 34)])
    assert at0(calm, positional.bad_situation) == 0


# ---- lines (the frame trap) -----------------------------------------------------------


DEFENCE = [
    opp(1, 104, 34),  # keeper: nearest THEIR goal at x = 105, left out
    opp(2, 95, 20),
    opp(3, 95, 34),
    opp(4, 96, 48),  # back line ~95.3 (HIGHEST x)
    opp(5, 80, 20),
    opp(6, 80, 34),
    opp(7, 81, 48),  # midfield ~80.3
    opp(8, 65, 30),
    opp(9, 66, 40),  # front ~65.5
]


def test_defending_back_line_is_the_highest_x_line():
    e = event(1, at=(60, 34), to=(85, 34), others=DEFENCE)
    lines = positional.defending_lines(e)
    assert [round(x, 2) for x in lines] == [65.5, 80.33, 95.33]
    # Back line (95.33) minus midfield (80.33), not front minus midfield.
    assert at0(e, positional.line_gap) == 15.0


def test_lines_broken_counts_lines_the_pass_crosses():
    # 60 -> 85 crosses the front (65.5) and midfield (80.3) lines, not the back.
    e = event(1, at=(60, 34), to=(85, 34), others=DEFENCE)
    assert at0(e, positional.lines_broken) == 2
    backwards = event(1, at=(85, 34), to=(60, 34), others=DEFENCE)
    assert at0(backwards, positional.lines_broken) == 0


# ---- overload (Ian's version) -------------------------------------------------------------


def test_overload_by_hand():
    # Ball at (75, 34), central lane (22.7-45.3); box x 65-95.
    # Attackers: carrier + 2 mates in the box = 3. Defenders: one in the box,
    # one just outside the lane (y 20), goal-side, within 10 m = 2 -> 3v2.
    others = [
        mate(2, 80, 34),
        mate(3, 85, 30),
        mate(1, 2, 34),  # our keeper, far away
        opp(1, 90, 34),
        opp(2, 100, 20),
        opp(3, 104, 34),  # their keeper: left out
    ]
    v = positional.overload(
        Events.of((H, A), [event(1, at=(75, 34), others=others)]), 0
    )
    assert (v.numerator, v.denominator) == (3, 2)
    assert v.value == 1.0  # central final third
    # Wide lane in midfield, 2v2: no overload.
    even = [
        mate(2, 50, 5),
        opp(1, 55, 5),
        opp(2, 45, 8),
        opp(3, 104, 34),
        mate(1, 2, 34),
    ]
    w = positional.overload(Events.of((H, A), [event(1, at=(50, 10), others=even)]), 0)
    assert (w.numerator, w.denominator, w.value) == (2, 2, 0.0)


# ---- pass difficulty (Ian's weights) -------------------------------------------------------


def test_pass_difficulty_by_hand():
    # From x 40 (middle third: zone 0.3) to x 65, 25 m straight forward
    # (distance 25/50 = 0.5, forwardness 1), crossing one line at 50; nobody
    # near the passer or the receiver.
    others = [opp(1, 50, 20), opp(2, 50, 48), opp(3, 104, 34), opp(4, 90, 34)]
    e = event(1, at=(40, 34), to=(65, 34), others=others)
    # lines: outfield x [50, 50, 90] -> lines [50, 50, 90] (3 groups) -> crosses
    # 50 and 50: 2 lines -> 2/3.
    want = 25 * 0 + 25 * (2 / 3) + 15 * 0.3 + 15 * 0 + 15 * 0.5 + 5 * 1
    assert at0(e, play.pass_difficulty) == round(want, 4)


# ---- speeds -------------------------------------------------------------------------


def test_name_tags():
    assert at0(event(1, type_="shot", speed=101), play.name_tag) == 1
    assert at0(event(1, type_="shot", speed=99), play.name_tag) == 0
    assert at0(event(1, at=(30, 34), to=(71, 34), length_m=41.0), play.name_tag) == 1
    assert at0(event(1, at=(30, 34), to=(69, 34), length_m=39.0), play.name_tag) == 0
    assert at0(event(1, type_="shot", speed=101), play.ball_speed) == 101


# ---- pressing, rhythm, threat --------------------------------------------------------------

# Home has the ball (p1) from 0', loses it at 0'20 (away intercepts), away
# passes under pressure in its own third, home wins it back with a tackle at
# 0'23 high up (x 85 in home's frame), and shoots at 0'30 (xG 0.35).
WINDOW = [
    event(1, 0, H, "pass", at=(40, 34), to=(60, 34), pid="p1"),
    event(2, 10, H, "dribble", at=(60, 34), to=(70, 34), pid="p1"),
    event(3, 20, H, "pass", "fail", at=(70, 34), to=(80, 34), pid="p1"),
    event(4, 20, A, "interception", at=(30, 34), pid="p1"),
    event(5, 21, A, "pass", at=(30, 34), to=(20, 34), pid="p2", under_pressure=True),
    event(6, 23, H, "tackle", at=(85, 34), pid="p2"),
    event(7, 30, H, "shot", "fail", at=(95, 34), pid="p3", xg=0.35, speed=90),
]


def window_events(items=WINDOW):
    return Events.of((H, A), items)


def val(fn, team=None, items=WINDOW):
    v = fn(window_events(items), 0, team)
    return v and round(v.value, 4)


def test_final_third_pressures():
    # Away touches in their own third (x < 35) under pressure: e5 only. Over
    # 30 s = 0.5 min -> 2 per minute.
    v = play.final_third_pressures(window_events(), 0, H)
    assert (v.numerator, v.denominator, v.value) == (1, 0.5, 2.0)


def test_high_turnover_and_counterpress():
    # Home loses it at 0'20 (e4), wins it back with the tackle at 0'23 (e6):
    # 3 s, within 5 s. The tackle is at home x 85: 20 m from goal (<= 40 m).
    assert val(play.high_turnovers, H) == 1
    v = play.counterpress_regains(window_events(), 0, H)
    assert (v.numerator, v.denominator) == (1, 1)
    assert v.evidence_event_ids == ["e6"]


def test_rhythm():
    # In-play gaps: 10, 10, 0, 1, 2, 7 -> sorted 0 1 2 7 10 10 -> median 4.5.
    assert val(play.seconds_between_actions) == 4.5


def test_momentum_halves_every_three_minutes():
    # Flat grid: home's pass 40 -> 60 (cells 6 -> 9) adds 0.03 at t = 0, the
    # dribble 60 -> 70 (9 -> 10) adds 0.01 at t = 10. Now = 180 s later.
    items = [*WINDOW[:2], event(9, 190, A, "clearance", at=(10, 34), pid="p9")]
    want = 0.03 * 0.5 ** (190 / 180) + 0.01 * 0.5 ** (180 / 180)
    assert val(play.momentum, items=items) == round(want, 4)


def test_threat():
    assert val(play.big_chances, H) == 1
    v = play.team_xt_added(window_events(), 0, H)
    assert (round(v.value, 4), v.denominator) == (0.04, 2)


def test_upper_hand_levels():
    # 10 home touches in the final third, 2 shots (xG 0.3 each), and 2 of 3
    # away touches in their own third under pressure.
    items = [
        event(k, k, H, "pass", at=(75, 34), to=(80, 34), pid="p1") for k in range(10)
    ]
    items += [
        event(20, 20, H, "shot", "fail", at=(95, 34), pid="p1", xg=0.3),
        event(21, 21, H, "shot", "fail", at=(95, 34), pid="p1", xg=0.3),
        event(22, 22, A, "clearance", at=(10, 34), pid="p2", under_pressure=True),
        event(23, 23, A, "clearance", at=(10, 34), pid="p3", under_pressure=True),
        event(24, 24, A, "clearance", at=(10, 34), pid="p4"),
    ]
    assert val(positional.upper_hand, H, items) == 2  # xG 0.6 >= 0.5: strong
    no_pressure = items[:-3] + [event(30, 30, A, "clearance", at=(10, 34), pid="p5")]
    assert val(positional.upper_hand, H, no_pressure) == 0


# ---- registry ------------------------------------------------------------------------


def test_every_metric_has_both_names_or_is_analyst_only():
    for m in METRICS.values():
        assert "analyst" in m.display_name and m.definition and m.unit, m.name


def test_last_event_metrics_reach_match_state():
    out = compute_all(window_events())
    assert {"pressure", "risk", "options", "xt_added"} - set(out[EVENT_KEY]) == {
        "xt_added"
    }
    # The last event is a shot: no xT added, but a ball speed.
    assert out[EVENT_KEY]["ball_speed"].value == 90


def test_registry_doc_is_up_to_date():
    from pathlib import Path

    doc = Path(__file__).resolve().parents[2] / "docs" / "metrics" / "REGISTRY.md"
    assert doc.read_text() == render(), (
        "run: uv run python -m scripts.export_metrics_doc"
    )
