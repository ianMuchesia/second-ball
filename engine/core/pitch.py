"""Pitch geometry. 105 x 68 m, 12 x 8 zones.

Internally the engine uses one absolute frame where the home team attacks +x.
`own()` converts between that and a team's own frame (attacking +x), which is
also the SPADL frame used in emitted events. The conversion is its own inverse.
"""

import math

LENGTH = 105.0
WIDTH = 68.0
ZONE_COLS = 12
ZONE_ROWS = 8
GOAL_Y = WIDTH / 2
GOAL_HALF_WIDTH = 7.32 / 2


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def on_pitch(x, y):
    return clamp(x, 0.0, LENGTH), clamp(y, 0.0, WIDTH)


def own(team, x, y):
    """Absolute <-> team frame. Team 0 (home) attacks +x already."""
    return (x, y) if team == 0 else (LENGTH - x, WIDTH - y)


def own_facing(team, deg):
    return deg % 360 if team == 0 else (deg + 180) % 360


def zone(x, y):
    col = min(int(x / (LENGTH / ZONE_COLS)), ZONE_COLS - 1)
    row = min(int(y / (WIDTH / ZONE_ROWS)), ZONE_ROWS - 1)
    return col, row


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def goal_distance(x, y):
    """Distance to the centre of the goal being attacked (team frame)."""
    return math.hypot(LENGTH - x, GOAL_Y - y)


def goal_angle(x, y):
    """Angle in radians the attacked goal mouth makes from (x, y) (team frame)."""
    a = math.atan2(GOAL_Y + GOAL_HALF_WIDTH - y, LENGTH - x)
    b = math.atan2(GOAL_Y - GOAL_HALF_WIDTH - y, LENGTH - x)
    return abs(a - b)


def bearing(a, b):
    """Degrees from a to b: 0 = +x, anticlockwise, [0, 360)."""
    return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 360
