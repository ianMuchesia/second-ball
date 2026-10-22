"""Phase 2a metrics. Pure functions of the events seen so far.

Each takes (events, lo, team): `events` is the match so far, `lo` the index of
the first event inside the window, `team` the team it is about (None for match
grain). Each returns a MetricValue (value + evidence_event_ids) or None when
the metric is undefined (e.g. PPDA with no defensive actions yet).

Evidence = the events that produced the number. When nothing contributed (zero
shots, say), the evidence is the events that were checked, so even a zero
points back at the feed.
"""

from core.contracts import MetricValue
from core.metrics.events import (
    DEFENSIVE_ACTIONS,
    FINAL_THIRD_X,
    LENGTH,
    OPEN_PLAY_PASSES,
    PASSES,
    PPDA_ZONE_X,
    RESTARTS,
    SHOTS,
    TOUCHES,
    Events,
    is_goal,
)


def value(v, evidence, checked=()):
    ids = [e.event_id for e in evidence] or [e.event_id for e in checked]
    return MetricValue(value=v, evidence_event_ids=ids) if ids else None


def window(ev: Events, lo: int):
    return ev.items[lo:]


def share(mine, theirs, checked):
    total = len(mine) + len(theirs)
    return value(len(mine) / total, mine, checked) if total else None


def possession_time(ev: Events, lo: int, team: str):
    """Share of in-play time the team had the ball.

    Each gap between consecutive events belongs to the team that owned the
    earlier event's possession. Gaps ending in a restart (dead ball), gaps
    after a goal (kick-off pause) and gaps across a period change are not
    in-play time.
    """
    mine, total, credited = 0.0, 0.0, []
    items, el = ev.items, ev.elapsed
    for i in range(lo, len(items) - 1):
        e, nxt = items[i], items[i + 1]
        if nxt.type in RESTARTS or is_goal(e) or nxt.period != e.period:
            continue
        gap = el[i + 1] - el[i]
        total += gap
        if ev.owner[e.possession_id] == team:
            mine += gap
            credited.append(e)
    if total <= 0:
        return None
    return value(mine / total, credited, window(ev, lo))


def possession_passes(ev: Events, lo: int, team: str):
    """Share of the match's passes (throw-ins excluded) made by the team."""
    passes = [e for e in window(ev, lo) if e.type in PASSES]
    mine = [e for e in passes if e.team_id == team]
    return share(mine, [e for e in passes if e.team_id != team], passes)


def passes_per_possession(ev: Events, lo: int, team: str):
    """Team passes / team possessions (possessions it owned in the window)."""
    events = window(ev, lo)
    owned = {e.possession_id for e in events if ev.owner[e.possession_id] == team}
    if not owned:
        return None
    passes = [e for e in events if e.type in PASSES and e.team_id == team]
    starts = [e for e in events if e.possession_id in owned]
    return value(len(passes) / len(owned), passes, starts)


def shots(ev: Events, lo: int, team: str):
    """Shots (open play, free kicks, penalties)."""
    events = [e for e in window(ev, lo) if e.team_id == team]
    taken = [e for e in events if e.type in SHOTS]
    return value(float(len(taken)), taken, events)


def xg(ev: Events, lo: int, team: str):
    """Sum of the feed's xG qualifier over the team's shots."""
    events = [e for e in window(ev, lo) if e.team_id == team]
    taken = [e for e in events if e.type in SHOTS]
    total = sum(float(e.qualifiers.get("xg", 0.0)) for e in taken)
    return value(total, taken, events)


def ppda(ev: Events, lo: int, team: str):
    """Passes allowed per defensive action: the opponent's open-play passes in
    its own 60% of the pitch / the team's tackles, interceptions and fouls in
    that same zone. Lower = more pressing. Undefined with no actions."""
    events = window(ev, lo)
    opp = ev.opponent(team)
    passes = [
        e
        for e in events
        if e.team_id == opp and e.type in OPEN_PLAY_PASSES and e.start_x < PPDA_ZONE_X
    ]
    # The defender's frame: the opponent's own 60% is x > 105 - 63.
    actions = [
        e
        for e in events
        if e.team_id == team
        and e.type in DEFENSIVE_ACTIONS
        and e.start_x > LENGTH - PPDA_ZONE_X
    ]
    if not actions:
        return None
    return value(len(passes) / len(actions), passes + actions)


def possession_changes_per_min(ev: Events, lo: int, team: None = None):
    """How often the ball changes team: possessions that start with the other
    team than the previous one, per minute of the window."""
    events = window(ev, lo)
    if len(events) < 2:
        return None
    minutes = (ev.elapsed[-1] - ev.elapsed[lo]) / 60
    changes, prev_pid, prev_owner = [], None, None
    for e in events:
        if e.possession_id == prev_pid:
            continue
        owner = ev.owner[e.possession_id]
        if prev_owner is not None and owner != prev_owner:
            changes.append(e)
        prev_pid, prev_owner = e.possession_id, owner
    if minutes <= 0:
        return None
    return value(len(changes) / minutes, changes, events)


def field_tilt(ev: Events, lo: int, team: str):
    """Share of all final-third touches (each team in its attacking third) that
    are the team's: who is camped in the other's half."""
    touches = [
        e for e in window(ev, lo) if e.type in TOUCHES and e.start_x >= FINAL_THIRD_X
    ]
    mine = [e for e in touches if e.team_id == team]
    return share(mine, [e for e in touches if e.team_id != team], touches)
