"""Teleports: the movement check (Ian's definition, 24 Oct 2026).

A teleport is any player moving faster than 10 m/s, or the ball faster than
40 m/s, between consecutive 0.1 s steps of normal playback. Each one is named
by its likely cause: the event emitted at or just before it.
"""

import math
from dataclasses import dataclass

PLAYER_MAX_MS = 10.0
BALL_MAX_MS = 40.0


@dataclass
class Teleport:
    sample: int  # index of the step it lands on
    what: str  # "player" or "ball"
    slot: int | None  # the player's slot (None for the ball)
    speed: float  # m/s over that step
    cause: str  # the event type at or just before it, or "half-time"


def find(tracks, events_by_id=None) -> list[Teleport]:
    """Every teleport in a match's tracks (sim.SimulatedMatch.tracks)."""
    samples = tracks.samples
    marks = sorted((i, eid) for eid, i in tracks.events.items())
    types = {eid: e.type for eid, e in (events_by_id or {}).items()}
    out = []

    def cause(i):
        before = [eid for j, eid in marks if j <= i]
        return types.get(before[-1], "event") if before else "kick-off"

    for i in range(1, len(samples)):
        a, b = samples[i - 1], samples[i]
        dt = b.t - a.t
        if b.period != a.period:
            # The second half starts where the first half's walk-back ended.
            for k, (p, q) in enumerate(zip(a.players, b.players, strict=True)):
                if p and q and math.dist(p[:2], q[:2]) > 0.5:
                    out.append(Teleport(i, "player", k, math.inf, "half-time"))
            continue
        if dt <= 0:
            continue
        for k, (p, q) in enumerate(zip(a.players, b.players, strict=True)):
            if p is None or q is None:
                if (p is None) != (q is None) and not _at_touchline(p or q):
                    out.append(Teleport(i, "player", k, math.inf, "appears/vanishes"))
                continue
            v = math.dist(p[:2], q[:2]) / dt
            if v > PLAYER_MAX_MS:
                out.append(Teleport(i, "player", k, v, cause(i)))
        v = math.dist(a.ball, b.ball) / dt
        if v > BALL_MAX_MS:
            out.append(Teleport(i, "ball", None, v, cause(i)))
    return out


def _at_touchline(p):
    """A sent-off player leaves the pitch at a touchline."""
    return p[1] <= 0.5 or p[1] >= 67.5
