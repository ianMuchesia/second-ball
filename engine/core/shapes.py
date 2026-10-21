"""Shape tables: one set of anchors per (phase, ball_side).

An anchor is (depth, y): depth 0 = the team's back line, 1 = its front line
(the engine turns depth into metres from where the ball is); y is metres
across the pitch in the team's own frame (attacking +x, so LEFT = high y,
y = 68 is the left touchline).

Clubs either write their shapes in YAML (`shapes:` with player roles) or get
them generated from their formation strings. RIGHT is always the mirror of
LEFT. Missing CENTRE = halfway between LEFT and RIGHT. Missing TRANSITION =
halfway between in and out of possession.
"""

from engine.core.pitch import GOAL_Y, WIDTH
from engine.league import mirror_role, parse_shape

PHASES = ("in_possession", "out_of_possession", "transition")
SIDES = ("left", "centre", "right")
SIDE_Y = {"left": WIDTH * 5 / 6, "centre": GOAL_Y, "right": WIDTH / 6}


def ball_side(y_own, cfg):
    s = cfg["shapes"]
    if y_own >= s["left_from_y"]:
        return "left"
    if y_own <= s["right_until_y"]:
        return "right"
    return "centre"


def mirror(shape, role_map=mirror_role):
    return {role_map(r): (d, WIDTH - y) for r, (d, y) in shape.items()}


def blend(a, b, t=0.5):
    return {
        r: (a[r][0] + t * (b[r][0] - a[r][0]), a[r][1] + t * (b[r][1] - a[r][1]))
        for r in a
    }


def explicit_table(shapes):
    """Table from a club's YAML `shapes:` (role -> [depth, y]); left given, right mirrored."""
    table = {}
    for phase in ("in_possession", "out_of_possession"):
        sides = getattr(shapes, phase)
        left = {r: tuple(a) for r, a in sides.left.items()}
        right = mirror(left)
        centre = (
            {r: tuple(a) for r, a in sides.centre.items()}
            if sides.centre
            else blend(left, right)
        )
        table[(phase, "left")], table[(phase, "centre")], table[(phase, "right")] = (
            left,
            centre,
            right,
        )
    _add_transition(table, shapes.transition)
    return table


def generic_roles():
    return [f"P{i}" for i in range(1, 11)]


def generic_table(profile):
    """Table from formation strings: lines back to front, spread across the width."""
    roles = generic_roles()
    table = {}
    settings = {
        # phase: (shape string, span, pull towards the ball side)
        "in_possession": (profile.in_possession_shape, 26 + 40 * profile.width, 0.3),
        "out_of_possession": (profile.formation, 22 + 18 * profile.width, 0.45),
    }
    for phase, (shape_str, span, pull) in settings.items():
        lines = parse_shape(shape_str)
        for side in SIDES:
            centre = GOAL_Y + pull * (SIDE_Y[side] - GOAL_Y)
            shape, it = {}, iter(roles)
            for i, n in enumerate(lines):
                depth = 0.0 if len(lines) == 1 else i / (len(lines) - 1)
                for y in _spread(n, min(span, WIDTH - 4), centre):
                    shape[next(it)] = (depth, y)
            table[(phase, side)] = shape
    _add_transition(table, None)
    return table


def _add_transition(table, explicit):
    for side in SIDES:
        if explicit is not None and getattr(explicit, side, None):
            table[("transition", side)] = {
                r: tuple(a) for r, a in getattr(explicit, side).items()
            }
        else:
            table[("transition", side)] = blend(
                table[("in_possession", side)], table[("out_of_possession", side)]
            )


def _spread(n, span, centre):
    if n == 1:
        return [centre]
    return [centre - span / 2 + span * i / (n - 1) for i in range(n)]


def table_for(profile):
    return explicit_table(profile.shapes) if profile.shapes else generic_table(profile)
