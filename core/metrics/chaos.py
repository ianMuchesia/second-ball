"""Phase 2b: control and chaos metrics. Same contract as basic.py:
f(events, lo, team) -> MetricValue | None, pure, evidence = event ids.

Control (per team): who is running the match.
Openness (match): both teams threatening, attack after attack.
Scrappiness (match, analyst only): the ball keeps changing hands.

These describe a match; they never judge it (an open match is not "better").
Thresholds live in core/metrics/config.yaml (TUNABLE, owner: Ian).
"""

import json
import statistics
from functools import cache
from itertools import pairwise
from pathlib import Path

import yaml

from core.contracts import MetricValue
from core.metrics import basic, xt
from core.metrics.basic import value, window
from core.metrics.events import (
    DEFENSIVE_ACTIONS,
    LOOSE_BALLS,
    PASSES,
    RESTARTS,
    SHOTS,
    Events,
    in_box,
    is_goal,
)

HERE = Path(__file__).resolve().parent


@cache
def config() -> dict:
    return yaml.safe_load((HERE / "config.yaml").read_text())


def grid() -> xt.XTGrid:
    return xt.load(config()["xt_version"])


def combine(parts: dict[str, MetricValue | None], weights: dict[str, float]):
    """Weighted mean of 0-1 parts; evidence = all parts' evidence."""
    have = {k: v for k, v in parts.items() if v is not None}
    if not have:
        return None
    total = sum(weights[k] for k in have)
    v = sum(weights[k] * p.value for k, p in have.items()) / total
    ids = list(dict.fromkeys(i for p in have.values() for i in p.evidence_event_ids))
    return MetricValue(value=v, evidence_event_ids=ids)


def scaled(v: MetricValue | None, f):
    return v and MetricValue(value=f(v.value), evidence_event_ids=v.evidence_event_ids)


# ---- control ------------------------------------------------------------------


def xt_share(ev: Events, lo: int, team: str):
    """Share of all positive xT added (successful passes and carries) that the
    team added: whose moves are creating the threat."""
    g = grid()
    gains = [(e, g.added(e)) for e in window(ev, lo)]
    gains = [(e, a) for e, a in gains if a is not None and a > 0]
    total = sum(a for _, a in gains)
    if total <= 0:
        return None
    mine = [(e, a) for e, a in gains if e.team_id == team]
    return value(
        sum(a for _, a in mine) / total, [e for e, _ in mine], [e for e, _ in gains]
    )


def control_index(ev: Events, lo: int, team: str):
    """Weighted mean of possession (time), field tilt and xT share (0-1)."""
    c = config()["control"]
    parts = {
        "possession_time": basic.possession_time(ev, lo, team),
        "field_tilt": basic.field_tilt(ev, lo, team),
        "xt_share": xt_share(ev, lo, team),
    }
    return combine(parts, c["weights"])


# ---- openness -----------------------------------------------------------------


def two_way_threat(ev: Events, lo: int, team: None = None):
    """The smaller of the two teams' xG in the window: high only when both
    teams are creating chances (one-sided pressure stays low)."""
    home, away = ev.teams
    a, b = basic.xg(ev, lo, home), basic.xg(ev, lo, away)
    if a is None or b is None:
        return None
    shots = [e for e in window(ev, lo) if e.type in SHOTS]
    return value(min(a.value, b.value), shots, window(ev, lo))


def possessions(ev: Events, lo: int):
    """[(possession_id, owner, [events])] in window order."""
    out = []
    for e in window(ev, lo):
        if not out or out[-1][0] != e.possession_id:
            out.append((e.possession_id, ev.owner[e.possession_id], []))
        out[-1][2].append(e)
    return out


def threat_event(ev: Events, owner: str, events, threshold: float):
    """First event where the owner shoots or gets the ball to xT > threshold."""
    g = grid()
    for e in events:
        if e.team_id != owner:
            continue
        if e.type in SHOTS:
            return e
        if g.added(e) is not None and g.at(e.end_x, e.end_y) > threshold:
            return e
        if e.type not in DEFENSIVE_ACTIONS and g.at(e.start_x, e.start_y) > threshold:
            return e
    return None


def threat_switches(ev: Events, lo: int, team: None = None):
    """How often the team creating threat changes sides: possessions with a
    shot or the ball reaching xT > threat_xt, counted each time the next such
    possession is the other team's."""
    th = config()["openness"]["threat_xt"]
    threats = []
    for _, owner, events in possessions(ev, lo):
        e = threat_event(ev, owner, events, th)
        if e is not None:
            threats.append((owner, e))
    switches = [e for (a, _), (b, e) in pairwise(threats) if a != b]
    return value(
        float(len(switches)), switches, [e for _, e in threats] or window(ev, lo)
    )


def transition_speed(ev: Events, lo: int, team: None = None):
    """Median seconds from winning the ball in open play to a shot or a
    successful move into the opponent's box, over regains that got there.
    Undefined when no regain did."""
    items = window(ev, lo)
    el = ev.elapsed[lo:]
    pos = {e.event_id: k for k, e in enumerate(items)}
    seconds, evidence = [], []
    poss = possessions(ev, lo)
    for (_, prev_owner, prev), (_, owner, events) in pairwise(poss):
        first = events[0]
        if owner == prev_owner or first.type in RESTARTS or any(map(is_goal, prev)):
            continue
        # The regain: the tackle or interception that ended the previous
        # possession, if the new owner made it; else the first touch.
        won = (
            prev[-1]
            if prev[-1].team_id == owner and prev[-1].type in DEFENSIVE_ACTIONS
            else first
        )
        end = next(
            (
                e
                for e in events
                if e.team_id == owner
                and (
                    e.type in SHOTS
                    or (
                        e.outcome == "success"
                        and e.type not in DEFENSIVE_ACTIONS
                        and in_box(e.end_x, e.end_y)
                    )
                )
            ),
            None,
        )
        if end is None:
            continue
        seconds.append(el[pos[end.event_id]] - el[pos[won.event_id]])
        evidence += [won, end]
    if not seconds:
        return None
    return value(statistics.median(seconds), evidence)


def openness_index(ev: Events, lo: int, team: None = None):
    """0-1: weighted mean of two-way threat, threat switches and transition
    speed, each scaled 0-1 (config.yaml). A window with no regain reaching a
    shot or the box scores 0 on speed."""
    o = config()["openness"]
    fast, slow = o["fast_s"], o["slow_s"]
    speed = transition_speed(ev, lo)
    if speed is None:
        checked = window(ev, lo)
        speed = value(0.0, [], checked) if checked else None
    else:
        speed = scaled(speed, lambda s: min(1.0, max(0.0, (slow - s) / (slow - fast))))
    parts = {
        "two_way_threat": scaled(
            two_way_threat(ev, lo), lambda v: min(1.0, v / o["xg_scale"])
        ),
        "threat_switches": scaled(
            threat_switches(ev, lo), lambda v: min(1.0, v / o["switches_scale"])
        ),
        "transition_speed": speed,
    }
    if any(p is None for p in parts.values()):
        return None
    return combine(parts, o["weights"])


def gap_bucket(gap: float) -> str:
    lo, hi = config()["openness"]["gap_buckets"]
    return f"<{lo}" if gap < lo else (f"{lo}-{hi}" if gap <= hi else f">{hi}")


@cache
def baseline() -> dict:
    v = config()["openness"]["baseline_version"]
    return json.loads((HERE / "artifacts" / f"openness_baseline_v{v}.json").read_text())


def openness_vs_expected(ev: Events, lo: int, team: None = None):
    """Openness minus the average openness of free_simulation fixtures with
    the same pre-match strength gap (0 = as open as usual for this kind of
    fixture). Needs the public strengths from the Match."""
    if ev.strengths is None:
        return None
    now = openness_index(ev, lo)
    if now is None:
        return None
    expected = baseline()["buckets"][gap_bucket(abs(ev.strengths[0] - ev.strengths[1]))]
    return MetricValue(
        value=now.value - expected["mean"], evidence_event_ids=now.evidence_event_ids
    )


# ---- scrappiness (analyst only) -------------------------------------------------


def short_possessions(ev: Events, lo: int, team: None = None):
    """Share of possessions in the window with fewer than N passes."""
    n = config()["scrappiness"]["short_possession_passes"]
    poss = possessions(ev, lo)
    if not poss:
        return None
    short = [
        events[0]
        for _, owner, events in poss
        if sum(e.type in PASSES and e.team_id == owner for e in events) < n
    ]
    return value(len(short) / len(poss), short, [p[2][0] for p in poss])


def loose_balls(ev: Events, lo: int, team: None = None):
    """Times the ball got away from a player (bad touches), per minute."""
    items = window(ev, lo)
    minutes = (ev.elapsed[-1] - ev.elapsed[lo]) / 60 if items else 0
    if minutes <= 0:
        return None
    loose = [e for e in items if e.type in LOOSE_BALLS]
    return value(len(loose) / minutes, loose, items)
