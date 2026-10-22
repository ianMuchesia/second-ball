"""Positional metrics from freeze frames (Ian's spec:
docs/metrics/pressure_risk_options.md). Phase 2c.

Per-event functions take (events, i) and describe event i from the acting
team's point of view. SPADL frame: the acting team attacks towards x = 105,
so its own goal is at (0, 34) and the DEFENDING team's own goal is at
(105, 34): the defenders' back line is their HIGHEST-x line.

Team functions (events, lo, team) aggregate the per-event values over a window.
"""

import math
from bisect import bisect_right

from core.contracts import MatchEvent, MetricValue, PlayerPosition
from core.metrics.basic import rate, value, window
from core.metrics.chaos import config
from core.metrics.events import LENGTH, SHOTS, TOUCHES, Events

WIDTH = 68.0
OWN_GOAL = (0.0, 34.0)  # acting team's own goal
THEIR_GOAL = (LENGTH, 34.0)  # defending team's own goal


def one(v: float, e: MatchEvent, num=None, den=None) -> MetricValue:
    return MetricValue(
        value=v, evidence_event_ids=[e.event_id], numerator=num, denominator=den
    )


def cached(name):
    """Per-event results are pure given the events before them: memoise."""

    def wrap(fn):
        def inner(ev: Events, i: int):
            k = (name, ev.items[i].event_id)
            if k not in ev.cache:
                ev.cache[k] = fn(ev, i)
            return ev.cache[k]

        inner.__name__, inner.__doc__, inner.__module__ = (
            fn.__name__,
            fn.__doc__,
            fn.__module__,
        )
        return inner

    return wrap


# ---- geometry -------------------------------------------------------------------


def dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def to_segment(p, a, b) -> float:
    """Distance from point p to the segment a-b."""
    ax, ay = a
    dx, dy = b[0] - ax, b[1] - ay
    length2 = dx * dx + dy * dy
    if length2 == 0:
        return dist(p, a)
    t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / length2))
    return dist(p, (ax + t * dx, ay + t * dy))


def angle_between(facing_deg: float, vec) -> float:
    """Degrees between a facing direction and a vector (0-180)."""
    to = math.degrees(math.atan2(vec[1], vec[0])) % 360
    d = abs(facing_deg - to) % 360
    return min(d, 360 - d)


def sides(e: MatchEvent):
    """(carrier, teammates, opponents) from the freeze frame."""
    carrier = next((p for p in e.freeze_frame if p.player_id == e.player_id), None)
    mates = [
        p
        for p in e.freeze_frame
        if p.team_id == e.team_id and p.player_id != e.player_id
    ]
    opps = [p for p in e.freeze_frame if p.team_id != e.team_id]
    return carrier, mates, opps


def keeper(players: list[PlayerPosition], goal) -> PlayerPosition | None:
    """The feed has no positions, so: the player nearest his own goal."""
    return min(players, key=lambda p: dist((p.x, p.y), goal), default=None)


def outfield(players, goal):
    k = keeper(players, goal)
    return [p for p in players if p is not k]


# ---- pressure -------------------------------------------------------------------


def weight(d: float) -> float:
    """1 within close_m, straight line down to weight_at_reach at reach_m, then 0."""
    c = config()["pressure"]
    if d <= c["close_m"]:
        return 1.0
    if d > c["reach_m"]:
        return 0.0
    frac = (c["reach_m"] - d) / (c["reach_m"] - c["close_m"])
    return c["weight_at_reach"] + (1 - c["weight_at_reach"]) * frac


def pressure_at(point, opps, facing_deg=None) -> float:
    """Sum of opponents' weights, doubled for one in front of where the player
    faces or goal-side (between him and the goal he attacks, x greater); both
    at once still x2. Scaled so one close opponent = 0.5."""
    c = config()["pressure"]
    total = 0.0
    for o in opps:
        w = weight(dist(point, (o.x, o.y)))
        if not w:
            continue
        vec = (o.x - point[0], o.y - point[1])
        in_front = (
            facing_deg is not None
            and angle_between(facing_deg, vec) < c["in_front_deg"]
        )
        goal_side = o.x > point[0]
        total += w * (c["blocking_factor"] if in_front or goal_side else 1.0)
    return min(1.0, total / c["full"])


@cached("pressure")
def pressure(ev: Events, i: int):
    """How hard the player on the ball is pressed (0-1)."""
    e = ev.items[i]
    carrier, _, opps = sides(e)
    facing = carrier.facing_deg if carrier else None
    return one(pressure_at((e.start_x, e.start_y), opps, facing), e)


def facing_own_goal(ev: Events, i: int):
    """1 if the player on the ball faces his own goal (120-240 degrees)."""
    e = ev.items[i]
    carrier, _, _ = sides(e)
    lo, hi = config()["facing_own_goal_deg"]
    return one(float(carrier is not None and lo <= carrier.facing_deg <= hi), e)


# ---- options --------------------------------------------------------------------


def offside_line(e: MatchEvent, opps) -> float:
    """x beyond which a teammate is offside: the second-last defender (keeper
    included), the ball, and only in the opponent's half."""
    xs = sorted((o.x for o in opps), reverse=True)
    second_last = xs[1] if len(xs) > 1 else (xs[0] if xs else LENGTH)
    return max(second_last, e.start_x, LENGTH / 2)


@cached("options")
def options(ev: Events, i: int):
    """Teammates he can pass to safely: no opponent within lane_clear_m of the
    straight lane, and not clearly offside."""
    e = ev.items[i]
    c = config()["options"]
    _, mates, opps = sides(e)
    line = offside_line(e, opps) + c["offside_m"]
    start = (e.start_x, e.start_y)
    safe = [
        m
        for m in mates
        if m.x <= line
        and all(
            to_segment((o.x, o.y), start, (m.x, m.y)) > c["lane_clear_m"] for o in opps
        )
    ]
    return one(float(len(safe)), e)


# ---- upper hand and risk ------------------------------------------------------------


def upper_hand_level(ev: Events, lo: int, team: str):
    """0 none, 1 upper hand, 2 strong (Ian, 2026-10-21), with the events used.

    Upper hand: >= min_touches in the opponent's final third AND >= min_shots
    AND constant pressure (at least half of the defending team's touches in
    its own third under pressure). Strong: also xG >= strong_xg. A window
    where the defenders never touched the ball in their own third shows no
    constant pressure, so no upper hand.
    """
    c = config()["upper_hand"]
    events = window(ev, lo)
    touches = [
        e
        for e in events
        if e.team_id == team and e.type in TOUCHES and e.start_x >= c["final_third_x"]
    ]
    shots = [e for e in events if e.team_id == team and e.type in SHOTS]
    defending = [
        e
        for e in events
        if e.team_id != team
        and e.type in TOUCHES
        and e.start_x < LENGTH - c["final_third_x"]
    ]
    pressed = [e for e in defending if e.under_pressure]
    constant = bool(defending) and len(pressed) >= c["pressure_share"] * len(defending)
    level = 0
    if len(touches) >= c["min_touches"] and len(shots) >= c["min_shots"] and constant:
        xg = sum(float(e.qualifiers.get("xg", 0.0)) for e in shots)
        level = 2 if xg >= c["strong_xg"] else 1
    return level, touches + shots + pressed, events


def upper_hand(ev: Events, lo: int, team: str):
    """0 none, 1 upper hand, 2 strong upper hand."""
    level, used, checked = upper_hand_level(ev, lo, team)
    return value(float(level), used if level else [], checked)


def upper_hand_checkpoint(ev: Events, lo: int, team: str):
    """Upper hand in the last completed fixed block (0-10', 10-20', ...)."""
    block = config()["upper_hand"]["checkpoint_min"] * 60
    if not ev.items or ev.now() < block:
        return None
    end_t = (ev.now() // block) * block
    hi = bisect_right(ev.elapsed, end_t)
    start = bisect_right(ev.elapsed, end_t - block)
    return upper_hand(ev.upto(hi), start, team)


@cached("risk")
def risk(ev: Events, i: int):
    """How costly losing the ball here would be (0-1): high in his own box,
    falling smoothly with distance from his own goal; about 0 in the final
    third when his team has the upper hand (last 10 min), no defender is left
    goal-side, or his team has an overload there."""
    e = ev.items[i]
    c = config()["risk"]
    d = dist((e.start_x, e.start_y), OWN_GOAL)
    r = math.exp(-((d / c["scale_m"]) ** 2))
    if e.start_x >= c["final_third_x"]:
        _, _, opps = sides(e)
        left = [o for o in outfield(opps, THEIR_GOAL) if o.x > e.start_x]
        view = ev.upto(i + 1)
        lo = bisect_right(view.elapsed, view.now() - 600)
        level, _, _ = upper_hand_level(view, lo, e.team_id)
        if level or not left or overload(ev, i).value > 0:
            r = c["upper_hand_risk"]
    return one(r, e)


@cached("bad_situation")
def bad_situation(ev: Events, i: int):
    """1 if risk >= 0.6 AND facing own goal AND (pressure >= 0.5 OR no options)."""
    c = config()["bad_situation"]
    bad = (
        risk(ev, i).value >= c["risk"]
        and facing_own_goal(ev, i).value == 1
        and (
            pressure(ev, i).value >= c["pressure"]
            or options(ev, i).value <= c["options"]
        )
    )
    return one(float(bad), ev.items[i])


# ---- lines ----------------------------------------------------------------------


def defending_lines(e: MatchEvent) -> list[float]:
    """x of the defending team's lines, ascending (the LAST is the back line:
    their goal is at x = 105). Outfielders split at the largest gaps in x."""
    _, _, opps = sides(e)
    xs = sorted(o.x for o in outfield(opps, THEIR_GOAL))
    if not xs:
        return []
    k = min(config()["lines"]["max_lines"], len(xs))
    gaps = sorted(range(1, len(xs)), key=lambda j: xs[j] - xs[j - 1], reverse=True)
    cuts = sorted(gaps[: k - 1])
    groups, prev = [], 0
    for cut in [*cuts, len(xs)]:
        groups.append(xs[prev:cut])
        prev = cut
    return [sum(g) / len(g) for g in groups]


@cached("lines_broken")
def lines_broken(ev: Events, i: int):
    """Defending lines a pass crosses going forward (start x < line < end x)."""
    e = ev.items[i]
    crossed = [x for x in defending_lines(e) if e.start_x < x < e.end_x]
    return one(float(len(crossed)), e)


@cached("line_gap")
def line_gap(ev: Events, i: int):
    """Metres between the defending team's back line and midfield line."""
    e = ev.items[i]
    lines = defending_lines(e)
    if len(lines) < 2:
        return None
    return one(lines[-1] - lines[-2], e)


# ---- overloads ------------------------------------------------------------------


def lane(y: float) -> tuple[float, float, str]:
    third = WIDTH / 3
    if y < third:
        return 0.0, third, "wide"
    if y < 2 * third:
        return third, 2 * third, "central"
    return 2 * third, WIDTH, "wide"


def danger(x: float, kind: str) -> float:
    d = config()["overload"]["danger"]
    if x >= 70:
        return d["central_final_third"] if kind == "central" else d["wide_final_third"]
    if x >= 35:
        return d["middle_third"]
    return d["own_third"]


def to_box(p, x0, x1, y0, y1) -> float:
    dx = max(x0 - p[0], 0.0, p[0] - x1)
    dy = max(y0 - p[1], 0.0, p[1] - y1)
    return math.hypot(dx, dy)


@cached("overload")
def overload(ev: Events, i: int):
    """Attackers minus defenders around the ball (keepers left out): a box 20 m
    towards goal and 10 m back in the ball's lane; defenders within 10 m of it
    and goal-side count too (they can still recover). Value = danger by place
    (1.0 central final third ... 0.1 own third) when attackers - defenders >= 1,
    else 0; numerator = attackers, denominator = defenders."""
    e = ev.items[i]
    c = config()["overload"]
    _, mates, opps = sides(e)
    bx, by = e.start_x, e.start_y
    y0, y1, kind = lane(by)
    x0, x1 = bx - c["behind_m"], bx + c["ahead_m"]
    attackers = [
        p
        for p in [
            *outfield(mates, OWN_GOAL),
            *[q for q in e.freeze_frame if q.player_id == e.player_id],
        ]
        if to_box((p.x, p.y), x0, x1, y0, y1) == 0
    ]
    defenders = [
        o
        for o in outfield(opps, THEIR_GOAL)
        if to_box((o.x, o.y), x0, x1, y0, y1) == 0
        or (o.x > bx and to_box((o.x, o.y), x0, x1, y0, y1) <= c["recover_m"])
    ]
    n_att, n_def = len(attackers), len(defenders)
    v = danger(bx, kind) if n_att - n_def >= 1 else 0.0
    return one(v, e, n_att, n_def)


# ---- team aggregates ----------------------------------------------------------------


def per_event(ev: Events, lo: int, fn, keep):
    """[(event, value)] for events in the window where keep(event)."""
    out = []
    for k in range(lo, len(ev.items)):
        if keep(ev.items[k]):
            v = fn(ev, k)
            if v is not None:
                out.append((ev.items[k], v.value))
    return out


def bad_situations(ev: Events, lo: int, team: str):
    """Times the team's player on the ball was in a bad situation."""
    vals = per_event(
        ev, lo, bad_situation, lambda e: e.team_id == team and e.type in TOUCHES
    )
    bad = [e for e, v in vals if v]
    return value(float(len(bad)), bad, [e for e, _ in vals])


def mean_pressure_on_ball(ev: Events, lo: int, team: str):
    """Average pressure on the team's player on the ball (0-1)."""
    vals = per_event(
        ev, lo, pressure, lambda e: e.team_id == team and e.type in TOUCHES
    )
    if not vals:
        return None
    return rate(sum(v for _, v in vals), len(vals), [e for e, _ in vals])


def team_line_gap(ev: Events, lo: int, team: str):
    """Average gap between the team's back line and midfield line while it
    defends (from the opponent's events' freeze frames)."""
    vals = per_event(
        ev, lo, line_gap, lambda e: e.team_id != team and e.type in TOUCHES
    )
    if not vals:
        return None
    return value(sum(v for _, v in vals) / len(vals), [e for e, _ in vals])


def overloads(ev: Events, lo: int, team: str):
    """Danger-weighted overloads the team created on the ball (sum of danger)."""
    vals = per_event(
        ev, lo, overload, lambda e: e.team_id == team and e.type in TOUCHES
    )
    found = [(e, v) for e, v in vals if v > 0]
    return value(sum(v for _, v in found), [e for e, _ in found], [e for e, _ in vals])
