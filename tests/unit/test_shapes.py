import random

import pytest

from engine.core.pitch import WIDTH
from engine.core.shape import TeamState, anchors, build_frame, lines
from engine.core.shapes import PHASES, SIDES, ball_side, mirror
from engine.core.sim import load_config
from engine.league import load_league

LEAGUE = load_league()
CFG = load_config()
BLOCK = 50
BALL_LEFT = (40.0, 60.0)  # home team frame: high y = left
BALL_RIGHT = (40.0, 8.0)


def riverside(side=0):
    return TeamState.start(side, LEAGUE["riverside_athletic"])


def spots_by_role(team, ball, phase):
    spots = anchors(team, ball, phase, BLOCK, CFG)
    return {team.roles.get(pl, "GK"): xy for pl, xy in spots.items()}


def bands(ball, phase):
    _, back, front = lines(phase, ball[0], BLOCK)
    return back, front


def in_front_band(x, back, front):
    return x >= back + 0.85 * (front - back)


def in_back_line(x, back):
    return abs(x - back) < 1.0


def test_ball_left_left_fb_high_right_fb_in_back_line():
    s = spots_by_role(riverside(), BALL_LEFT, "in_possession")
    back, front = bands(BALL_LEFT, "in_possession")
    assert in_front_band(s["LB"][0], back, front)
    assert in_back_line(s["RB"][0], back)
    assert s["LB"][1] > WIDTH - 10  # high and wide on the left


def test_ball_right_is_the_mirror():
    s = spots_by_role(riverside(), BALL_RIGHT, "in_possession")
    back, front = bands(BALL_RIGHT, "in_possession")
    assert in_front_band(s["RB"][0], back, front)
    assert in_back_line(s["LB"][0], back)
    assert s["RB"][1] < 10


def test_ball_left_front_five_and_base_two():
    s = spots_by_role(riverside(), BALL_LEFT, "in_possession")
    back, front = bands(BALL_LEFT, "in_possession")
    front_five = {r for r, (x, _) in s.items() if in_front_band(x, back, front)}
    assert front_five == {"LB", "LW", "ST", "RCM", "RW"}
    back_three = {r for r, (x, _) in s.items() if r != "GK" and in_back_line(x, back)}
    assert back_three == {"LCB", "RCB", "RB"}
    assert s["LW"][1] < s["LB"][1]  # winger inside the full-back


def test_away_team_shape_flips_with_the_pitch():
    # Away attacks -x: its left is low absolute y, so the mirror case applies.
    team = riverside(side=1)
    ball_on_its_left = (65.0, 8.0)
    s = spots_by_role(team, ball_on_its_left, "in_possession")
    assert s["LB"][0] < s["RB"][0]  # LB further up the pitch (towards x = 0)


@pytest.mark.parametrize(
    ("ball", "steps_up"),
    [(BALL_LEFT, "LCM"), (BALL_RIGHT, "RCM"), ((40.0, 34.0), "LCM")],
)
def test_out_of_possession_ball_side_cm_steps_up_beside_the_9(ball, steps_up):
    table = riverside().table
    shape = table[("out_of_possession", ball_side(ball[1], CFG))]
    front_two = {r for r, (d, _) in shape.items() if d == 1.0}
    assert front_two == {"ST", steps_up}


@pytest.mark.parametrize("club", sorted(LEAGUE))
def test_every_club_has_nine_shapes_and_right_mirrors_left(club):
    team = TeamState.start(0, LEAGUE[club])
    assert set(team.table) == {(p, s) for p in PHASES for s in SIDES}
    if LEAGUE[club].shapes:
        for phase in ("in_possession", "out_of_possession"):
            assert team.table[(phase, "right")] == mirror(team.table[(phase, "left")])


def test_frames_move_part_way_towards_the_shape():
    cfg = {**CFG, "frame_noise_m": 0.0}
    teams = (riverside(0), TeamState.start(1, LEAGUE["ironvale"]))
    phases = {0: "in_possession", 1: "out_of_possession"}
    blocks = {0: BLOCK, 1: 30}
    args = (cfg, teams, 0, 9, BALL_LEFT, 8.0, False, blocks, phases)
    snapped = build_frame(random.Random(1), *args)
    previous = {k: (x + 10.0, y) for k, (x, y) in snapped.shape_positions.items()}
    moved = build_frame(random.Random(1), *args, previous)
    key = (0, 4)  # Riverside LB, not the carrier or the presser
    assert moved.shape_positions[key][0] == pytest.approx(
        snapped.shape_positions[key][0] + 5.0
    )


def test_red_card_most_advanced_player_fills_the_gap():
    team = riverside()
    lcb = next(p for p, r in team.roles.items() if r == "LCB")
    team.send_off(lcb)
    assert len(team.roles) == 9
    assert "LCB" in team.roles.values()
    assert "LCM" not in team.roles.values()  # LCM (front two) dropped back
