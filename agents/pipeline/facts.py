"""What code knows about a moment, in words a line may use: the score and red
cards so far, how a goal was made, who was sent off and why; plus counts
(passes in the move, which counter goal this is, shirt number) a line may
quote as digits or words.

A goal "came from a counter behind the full-back" only if the move that ended
in it passes the detector's own counter rule (core.moments), run here on that
move alone; nothing is inferred from nearby moments.
Names and positions come from the published team sheet (Match.lineups).
A red card is "on a counter" if the fouled team had won the ball in its own
half, moved it forward at least min_forward_m and was fouled within within_s
(the detector's counter thresholds); "last-man" if no other outfield player
of the fouling team was goal-side of the foul (Ian, 2026-10-22). The feed has
no positions, so the player is named by shirt number only.
"""

from collections import Counter

from agents.mcp_server.data import MatchData
from agents.pipeline.display import display_for
from agents.pipeline.lineups import said
from agents.pipeline.models import MatchContext, NarrationTask, Persona
from core.contracts import Moment
from core.metrics import positional
from core.metrics.events import PASSES
from core.metrics.state import score
from core.moments import MomentDetector, config

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
    reds = [e for e in so_far.items if e.outcome == "red_card"]
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
        sent_off=dict(Counter(e.team_id for e in reds)),
        # On the pitch: the starting XIs minus anyone sent off so far.
        players={
            p.player_id: p.name
            for p in m.lineups
            if p.starting and p.player_id not in {e.player_id for e in reds}
        },
        lineup=list(m.lineups),
    )


def counter_side(data: MatchData, k: int) -> str | None:
    """'left' or 'right' (the defenders' side) if the move that ended in event k
    had a counter behind a full-back, by the detector's rule; else None."""
    ev = data.events
    j = move_start(data, k)
    probe = MomentDetector()  # fresh: it only counts, it cannot fire on a 1st counter
    for i in range(j, k + 1):
        before = dict(probe.counters)
        probe.counter(ev, i)
        for (_, side), n in probe.counters.items():
            if n > before.get((_, side), 0):
                return side
    return None


def move_start(data: MatchData, k: int) -> int:
    pid = data.events.items[k].possession_id
    j = k
    while j > 0 and data.events.items[j - 1].possession_id == pid:
        j -= 1
    return j


def shirt(player_id: str) -> int | None:
    tail = player_id.rsplit("-", 1)[-1]
    return int(tail) if tail.isdigit() else None


def red_card(data: MatchData, moment: Moment) -> tuple[dict[str, str], dict[str, int]]:
    """Who was sent off and why, from the foul event and the move before it."""
    ev = data.events
    k = next(data.by_id[i] for i in moment.evidence_event_ids)
    foul = ev.items[k]
    ctx = context_at(data, moment)
    number = shirt(foul.player_id)
    team = ctx.team_names[foul.team_id]
    sheet = next((p for p in ctx.lineup if p.player_id == foul.player_id), None)
    who = (
        f"{team}'s {said(sheet)} {sheet.name} (number {sheet.shirt_number})"
        if sheet
        else f"{team}'s number {number}"
    )
    # The fouled team's move: its events just before the foul.
    j = k - 1
    while j >= 0 and ev.items[j].team_id == foul.team_id:
        j -= 1
    on_counter = False
    if j >= 0:
        c = config()["counter"]
        won = MomentDetector().regain_time(ev, j)
        if won is not None:
            regain = ev.items[won[0]]
            own = [e for e in ev.items[won[0] : j + 1] if e.team_id == regain.team_id]
            forward = max(e.end_x for e in own) - regain.start_x
            on_counter = (
                regain.start_x <= c["regain_max_x"]
                and forward >= c["min_forward_m"]
                and ev.elapsed[k] - won[1] <= c["within_s"]
            )
    _, mates, _ = positional.sides(foul)
    goal_side = [
        p for p in positional.outfield(mates, positional.OWN_GOAL) if p.x < foul.start_x
    ]
    last_man = not goal_side
    reason = ("last-man foul" if last_man else "foul") + (
        " on a counter" if on_counter else ""
    )
    facts = {
        "sent_off": who,
        "reason": reason,
        "claim": f"{who} was sent off for a {reason}.",
    }
    # With a team sheet the shirt is checked against it ("number 5
    # Stonebridge"); without one, the number is a count the line may quote.
    return facts, ({"shirt_number": number} if number is not None and not sheet else {})


def facts_for(data: MatchData, moment: Moment) -> dict[str, str]:
    """Goal from a counter behind a full-back: the build-up, the zone and, if it
    happened before in this match, which time this is. Red card: who and why."""
    if moment.kind == "red_card_impact":
        return red_card(data, moment)[0]
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
    full_back = next(
        (
            p
            for p in ctx.lineup
            if p.team_id == other
            and p.player_id in ctx.players
            and p.position in ({"LB", "LWB"} if side == "left" else {"RB", "RWB"})
        ),
        None,
    )
    if full_back is not None:
        out["exposed_player"] = (
            f"{full_back.name}, {ctx.team_names[other]}'s {said(full_back)}"
        )
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


def counts_for(data: MatchData, moment: Moment) -> dict[str, int]:
    """Counts a line may quote: passes in a goal's move, which counter goal
    this is, the sent-off player's shirt number."""
    if moment.kind == "red_card_impact":
        return red_card(data, moment)[1]
    if moment.kind != "goal" or moment.team is None:
        return {}
    k = last_index(data, moment)
    move = data.events.items[move_start(data, k) : k + 1]
    out = {
        "passes_in_move": sum(
            1 for e in move if e.team_id == moment.team and e.type in PASSES
        )
    }
    side = counter_side(data, k)
    if side is not None:
        out["counter_goals"] = 1 + sum(
            1
            for m in data.moments
            if m.kind == "goal"
            and m.team == moment.team
            and last_index(data, m) < k
            and counter_side(data, last_index(data, m)) == side
        )
    return out


def task_for(
    data: MatchData,
    moment: Moment,
    persona: Persona,
    languages: list[str] | None = None,
) -> NarrationTask:
    extra = {} if languages is None else {"languages": languages}
    ctx = context_at(data, moment)
    return NarrationTask(
        moment=moment,
        context=ctx,
        persona=persona,
        facts=facts_for(data, moment),
        counts=counts_for(data, moment),
        display=display_for(data, moment, ctx, persona),
        **extra,
    )
