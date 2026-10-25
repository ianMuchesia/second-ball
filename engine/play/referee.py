"""The referee: on the pitch and moving, under the same limits as a player.

He runs the diagonal system (corner to corner, his left; the assistants have
the other two corners), staying 15-25 m from the ball where he can see play,
never in the way. Recorded in the tracks as one more slot, "referee".
"""

import math

from engine.core.pitch import GOAL_Y, LENGTH, WIDTH
from engine.play.player import Player

SLOT = "referee"


def make():
    return Player(("ref", 0), SLOT, "officials", False, LENGTH / 2 - 8.0, GOAL_Y + 12.0)


def spot(ball, cfg):
    """Where he wants to be for the ball at `ball`: on the diagonal from
    (16, 56) to (89, 12), kept 15-25 m from the ball."""
    bx, by = ball
    x = min(max(bx, 16.0), LENGTH - 16.0)
    y = 56.0 - (x - 16.0) * 44.0 / (LENGTH - 32.0)
    d = math.dist((x, y), (bx, by))
    lo, hi = cfg["near_m"], cfg["far_m"]
    if d < lo or d > hi:
        want = min(max(d, lo), hi)
        ux, uy = ((x - bx) / d, (y - by) / d) if d > 0.1 else (0.0, -1.0)
        x, y = bx + ux * want, by + uy * want
    return min(max(x, 2.0), LENGTH - 2.0), min(max(y, 2.0), WIDTH - 2.0)


def step(ref, ball, dt, player_cfg, cfg):
    """Move him one step towards his spot: walking near it, jogging, or
    running when play has got away from him (never faster than `top_ms`)."""
    target = spot(ball, cfg)
    far = math.dist(ref.pos, target)
    cap = (
        cfg["walk_ms"] if far < 3.0 else cfg["jog_ms"] if far < 10.0 else cfg["top_ms"]
    )
    ref.move(target, cap, dt, player_cfg)
    ref.face(ball, dt, player_cfg)
