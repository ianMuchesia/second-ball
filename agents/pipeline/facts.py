"""What code knows about a moment, in words a line may use: the score and red
cards so far, and how a goal was made.

A goal "came from a counter behind the full-back" only if the move that ended
in it passes the detector's own counter rule (core.moments), run here on that
move alone; nothing is inferred from nearby moments.
"""

from collections import Counter

from agents.mcp_server.data import MatchData
from agents.pipeline.models import MatchContext
from core.contracts import Moment
from core.metrics.state import score
from core.moments import MomentDetector

TEAM_NAMES = {"riverside_athletic": "Riverside", "harbour_town": "Harbour"}
ORDINAL = {2: "second", 3: "third"}


def last_index(data: MatchData, moment: Moment) -> int:
    return max(data.by_id[i] for i in moment.evidence_event_ids)


def context_at(data: MatchData, moment: Moment) -> MatchContext:
    """What a broadcaster knows at the moment: score and red cards up to its
    last evidence event."""
    so_far = data.events.upto(last_index(data, moment) + 1)
    s = score(so_far)
    m = data.match
    return MatchContext(
        match_id=m.match_id,
        home=m.home_team,
        away=m.away_team,
        team_names={
            t: TEAM_NAMES.get(t, t.replace("_", " ").title())
            for t in (m.home_team, m.away_team)
        },
        score=(s.home, s.away),
        minute=moment.clock.minute,
        sent_off=dict(
            Counter(e.team_id for e in so_far.items if e.outcome == "red_card")
        ),
    )


def counter_side(data: MatchData, k: int) -> str | None:
    """'left' or 'right' (the defenders' side) if the move that ended in event k
    had a counter behind a full-back, by the detector's rule; else None."""
    ev = data.events
    pid = ev.items[k].possession_id
    j = k
    while j > 0 and ev.items[j - 1].possession_id == pid:
        j -= 1
    probe = MomentDetector()  # fresh: it only counts, it cannot fire on a 1st counter
    for i in range(j, k + 1):
        before = dict(probe.counters)
        probe.counter(ev, i)
        for (_, side), n in probe.counters.items():
            if n > before.get((_, side), 0):
                return side
    return None


def facts_for(data: MatchData, moment: Moment) -> dict[str, str]:
    """For a goal from a counter behind a full-back: the build-up, the zone and,
    if it happened before in this match, which time this is."""
    if moment.kind != "goal" or moment.team is None:
        return {}
    k = last_index(data, moment)
    side = counter_side(data, k)
    if side is None:
        return {}
    ctx = context_at(data, moment)
    other = ctx.away if moment.team == ctx.home else ctx.home
    zone = f"behind {ctx.team_names[other]}'s {side}-back"
    out = {"build_up": "counter-attack", "exploited_zone": zone, "side": side}
    n = 1 + sum(
        1
        for m in data.moments
        if m.kind == "goal"
        and m.team == moment.team
        and last_index(data, m) < k
        and counter_side(data, last_index(data, m)) == side
    )
    if n > 1:
        out["pattern"] = (
            f"{ORDINAL.get(n, 'another')} counter goal {zone} in this match"
        )
    return out
