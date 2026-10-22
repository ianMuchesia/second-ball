"""Phase 2c: pressing, rhythm, threat, pass quality and speeds.

Team functions are f(events, lo, team) like basic.py; per-event functions are
f(events, i). Thresholds: core/metrics/config.yaml (TUNABLE, owner: Ian).
"""

import math
import statistics
from itertools import pairwise

from core.metrics import positional as pos
from core.metrics.basic import rate, value, window
from core.metrics.chaos import config, grid, possessions
from core.metrics.events import (
    DEFENSIVE_ACTIONS,
    LENGTH,
    PASSES,
    RESTARTS,
    SHOTS,
    TOUCHES,
    Events,
    in_box,
    is_goal,
)


def minutes(ev: Events, lo: int) -> float:
    return (ev.elapsed[-1] - ev.elapsed[lo]) / 60 if lo < len(ev.items) else 0.0


# ---- pressing -------------------------------------------------------------------


def final_third_pressures(ev: Events, lo: int, team: str):
    """Pressures per minute in the team's attacking third: opponent touches in
    their own third made under pressure (an attacker within 2 m)."""
    x = LENGTH - config()["pressing"]["final_third_x"]
    events = window(ev, lo)
    pressed = [
        e
        for e in events
        if e.team_id != team
        and e.type in TOUCHES
        and e.start_x < x
        and e.under_pressure
    ]
    return rate(len(pressed), minutes(ev, lo), pressed, events)


def regains(ev: Events, lo: int, team: str):
    """[(regain event, elapsed, previous possession's events)] for possessions
    the team won in open play (not a restart, not after a goal)."""
    poss = possessions(ev, lo)
    at = {e.event_id: ev.elapsed[lo + k] for k, e in enumerate(window(ev, lo))}
    out = []
    for (_, prev_owner, prev), (_, owner, events) in pairwise(poss):
        first = events[0]
        if owner != team or prev_owner == team:
            continue
        if first.type in RESTARTS or any(map(is_goal, prev)):
            continue
        won = (
            prev[-1]
            if prev[-1].team_id == team and prev[-1].type in DEFENSIVE_ACTIONS
            else first
        )
        out.append((won, at[won.event_id], prev))
    return out


def high_turnovers(ev: Events, lo: int, team: str):
    """Regains within 40 m of the opponent's goal."""
    reach = config()["pressing"]["high_turnover_m"]
    high = [
        won
        for won, _, _ in regains(ev, lo, team)
        if math.hypot(LENGTH - won.start_x, 34 - won.start_y) <= reach
    ]
    return value(float(len(high)), high, window(ev, lo))


def counterpress_regains(ev: Events, lo: int, team: str):
    """Share of balls lost in open play that the team won back within 5 s.
    numerator = quick regains, denominator = balls lost."""
    limit = config()["pressing"]["counterpress_s"]
    poss = possessions(ev, lo)
    at = {e.event_id: ev.elapsed[lo + k] for k, e in enumerate(window(ev, lo))}
    losses, quick = [], []
    for k in range(len(poss) - 1):
        (_, owner, events), (_, nxt_owner, nxt) = poss[k], poss[k + 1]
        if owner != team or nxt_owner == team or nxt[0].type in RESTARTS:
            continue
        if any(map(is_goal, events)):
            continue
        lost_at = at[events[-1].event_id]
        losses.append(events[-1])
        # The team's next possession, if won in open play (not a restart). The
        # regain is the tackle or interception that ended the opponent's
        # possession, when the team made it; else its first touch.
        j = next((j for j in range(k + 2, len(poss)) if poss[j][1] == team), None)
        if j is None or poss[j][2][0].type in RESTARTS:
            continue
        prev, first = poss[j - 1][2], poss[j][2][0]
        won = (
            prev[-1]
            if prev[-1].team_id == team and prev[-1].type in DEFENSIVE_ACTIONS
            else first
        )
        if at[won.event_id] - lost_at <= limit:
            quick.append(won)
    return rate(len(quick), len(losses), quick, losses)


# ---- rhythm ---------------------------------------------------------------------


def actions_per_minute(ev: Events, lo: int, team: str):
    """On-ball actions per minute of the team's own possession time."""
    poss_time = 0.0
    items, el = ev.items, ev.elapsed
    for k in range(lo, len(items) - 1):
        e, nxt = items[k], items[k + 1]
        if nxt.type in RESTARTS or is_goal(e) or nxt.period != e.period:
            continue
        if ev.owner[e.possession_id] == team:
            poss_time += el[k + 1] - el[k]
    acts = [
        e
        for e in window(ev, lo)
        if e.team_id == team and e.type in TOUCHES and ev.owner[e.possession_id] == team
    ]
    return rate(len(acts), poss_time / 60, acts) if poss_time > 0 else None


def seconds_between_actions(ev: Events, lo: int, team: None = None):
    """Median in-play seconds between consecutive events."""
    gaps, used = [], []
    items, el = ev.items, ev.elapsed
    for k in range(lo, len(items) - 1):
        e, nxt = items[k], items[k + 1]
        if nxt.type in RESTARTS or is_goal(e) or nxt.period != e.period:
            continue
        gaps.append(el[k + 1] - el[k])
        used.append(nxt)
    return value(statistics.median(gaps), used) if gaps else None


def momentum(ev: Events, lo: int, team: None = None):
    """Exponentially weighted xT added, home minus away (half-life 3 min):
    > 0 home on top right now, < 0 away. Evidence: moves still weighing > 5%."""
    half = config()["rhythm"]["momentum_half_life_s"]
    g = grid()
    home = ev.teams[0]
    now = ev.now()
    total, used = 0.0, []
    for k in range(lo, len(ev.items)):
        e = ev.items[k]
        added = g.added(e)
        if added is None:
            continue
        w = 0.5 ** ((now - ev.elapsed[k]) / half)
        total += (1 if e.team_id == home else -1) * added * w
        if w > 0.05:
            used.append(e)
    return value(total, used, window(ev, lo))


# ---- threat ---------------------------------------------------------------------


@pos.cached("xt_added")
def xt_added(ev: Events, i: int):
    """xT added by this pass or carry (successful moves only)."""
    e = ev.items[i]
    added = grid().added(e)
    return None if added is None else pos.one(added, e)


def team_xt_added(ev: Events, lo: int, team: str):
    """Net xT added by the team's successful passes and carries.
    numerator = xT, denominator = moves (so value / move is available)."""
    g = grid()
    moves = [e for e in window(ev, lo) if e.team_id == team and g.added(e) is not None]
    total = sum(g.added(e) for e in moves)
    return value(total, moves, window(ev, lo), total, len(moves))


def big_chances(ev: Events, lo: int, team: str):
    """Shots with xG >= 0.3."""
    th = config()["threat"]["big_chance_xg"]
    events = [e for e in window(ev, lo) if e.team_id == team]
    big = [
        e for e in events if e.type in SHOTS and float(e.qualifiers.get("xg", 0)) >= th
    ]
    return value(float(len(big)), big, events)


# ---- pass quality ---------------------------------------------------------------


def length(e) -> float:
    return float(
        e.qualifiers.get(
            "length_m", math.hypot(e.end_x - e.start_x, e.end_y - e.start_y)
        )
    )


def team_passes(ev: Events, lo: int, team: str):
    return [
        (lo + k, e)
        for k, e in enumerate(window(ev, lo))
        if e.team_id == team and e.type in PASSES
    ]


def pass_distance(ev: Events, lo: int, team: str):
    """Average pass length (m)."""
    passes = [e for _, e in team_passes(ev, lo, team)]
    if not passes:
        return None
    return value(sum(map(length, passes)) / len(passes), passes)


def pass_accuracy(ev: Events, lo: int, team: str):
    """Completed passes / passes."""
    passes = [e for _, e in team_passes(ev, lo, team)]
    ok = [e for e in passes if e.outcome == "success"]
    return rate(len(ok), len(passes), ok, passes)


def lines_broken_per_pass(ev: Events, lo: int, team: str):
    """Defending lines crossed per completed pass."""
    done = [(k, e) for k, e in team_passes(ev, lo, team) if e.outcome == "success"]
    if not done:
        return None
    total = sum(pos.lines_broken(ev, k).value for k, _ in done)
    return rate(total, len(done), [e for _, e in done])


def zone(e) -> float:
    z = config()["pass_difficulty"]["zone"]
    if in_box(e.start_x, e.start_y):
        return z["box"]
    if e.start_x >= 70:
        return z["final_third"]
    if e.start_x >= 35:
        return z["middle_third"]
    return z["own_third"]


def difficulty_parts(ev: Events, i: int) -> dict[str, float]:
    """Each part 0-1 (docs/metrics/pass_difficulty.md)."""
    e = ev.items[i]
    c = config()["pass_difficulty"]
    _, _, opps = pos.sides(e)
    d = length(e)
    return {
        "passer_pressure": pos.pressure(ev, i).value,
        "lines_broken": pos.lines_broken(ev, i).value / config()["lines"]["max_lines"],
        "zone": zone(e),
        "receiver_pressure": pos.pressure_at((e.end_x, e.end_y), opps),
        "distance": min(1.0, d / c["distance_full_m"]),
        "forwardness": max(0.0, e.end_x - e.start_x) / d if d > 0 else 0.0,
    }


@pos.cached("pass_difficulty")
def pass_difficulty(ev: Events, i: int):
    """0-100: weighted sum of passer pressure, lines broken, zone, receiver
    pressure, distance and forwardness (Ian's weights)."""
    e = ev.items[i]
    if e.type not in PASSES:
        return None
    w = config()["pass_difficulty"]["weights"]
    parts = difficulty_parts(ev, i)
    return pos.one(sum(w[k] * parts[k] for k in w), e)


def mean_pass_difficulty(ev: Events, lo: int, team: str):
    """Average difficulty (0-100) of the team's passes."""
    passes = team_passes(ev, lo, team)
    if not passes:
        return None
    total = sum(pass_difficulty(ev, k).value for k, _ in passes)
    return value(total / len(passes), [e for _, e in passes])


# ---- speeds ---------------------------------------------------------------------


def ball_speed(ev: Events, i: int):
    """Ball speed of a pass or shot (km/h), from the feed."""
    e = ev.items[i]
    if e.ball_speed_kmh is None or e.type not in PASSES | SHOTS:
        return None
    return pos.one(e.ball_speed_kmh, e)


@pos.cached("name_tag")
def name_tag(ev: Events, i: int):
    """1 when the event earns an on-screen name tag: a shot at >= 100 km/h or a
    pass of >= 45 m (not a goal kick or a keeper's clearance), and the same
    player has not had a tag in the last 5 minutes."""
    e = ev.items[i]
    c = config()["speeds"]
    if not tag_worthy(e, c):
        return pos.one(0.0, e)
    since = ev.elapsed[i] - c["name_tag_cooldown_s"]
    for k in range(i - 1, -1, -1):
        if ev.elapsed[k] <= since:
            break
        if ev.items[k].player_id == e.player_id and name_tag(ev, k).value:
            return pos.one(0.0, e)
    return pos.one(1.0, e)


def tag_worthy(e, c) -> bool:
    if e.type in SHOTS:
        return (e.ball_speed_kmh or 0) >= c["name_tag_shot_kmh"]
    if e.type not in PASSES or e.type == "goalkick":
        return False
    # A keeper's long kick is a clearance in all but name.
    own = [p for p in e.freeze_frame if p.team_id == e.team_id]
    keeper = pos.keeper(own, pos.OWN_GOAL)
    if keeper is not None and keeper.player_id == e.player_id:
        return False
    return length(e) >= c["name_tag_pass_m"]


def fastest_shot(ev: Events, lo: int, team: str):
    """Fastest shot (km/h)."""
    shots = [
        e
        for e in window(ev, lo)
        if e.team_id == team and e.type in SHOTS and e.ball_speed_kmh is not None
    ]
    if not shots:
        return None
    best = max(shots, key=lambda e: e.ball_speed_kmh)
    return value(best.ball_speed_kmh, [best])


def name_tags(ev: Events, lo: int, team: str):
    """Events that earn a name tag (fast shots, 45 m+ passes; 5-min cooldown)."""
    tagged = [
        e
        for k, e in enumerate(window(ev, lo))
        if e.team_id == team and name_tag(ev, lo + k).value
    ]
    return value(float(len(tagged)), tagged, window(ev, lo))
