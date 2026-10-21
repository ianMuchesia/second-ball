"""MatchState from events: score, clock and every registered metric."""

from core.contracts import Clock, MatchState, Score
from core.metrics.events import SHOTS, Events
from core.metrics.registry import compute_all


def score(events: Events) -> Score:
    home, away = events.teams
    goals = {home: 0, away: 0}
    for e in events.items:
        if e.outcome == "owngoal":
            goals[events.opponent(e.team_id)] += 1
        elif e.type in SHOTS and e.outcome == "success":
            goals[e.team_id] += 1
    return Score(home=goals[home], away=goals[away])


def match_state(events: Events) -> MatchState:
    last = events.items[-1]
    return MatchState(
        score=score(events),
        clock=Clock(period=last.period, minute=last.minute, second=last.second),
        metrics=compute_all(events),
    )
