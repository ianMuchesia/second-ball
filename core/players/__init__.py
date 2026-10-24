"""Player stats (Phase 5): every number counted by code from match events.

Each stat lists the event types it comes from (`sources`); a stat whose
sources the engine never produces is not offered (stat_groups.yaml `omitted`,
docs/DATASHEET.md). A player's card is picked by position from the team sheet
(stat_groups.yaml, owner: Ian).

Stats are built from contributions: (event index, value, numerator,
denominator). Summing them up to an event gives the stat at that moment, so a
card can be shown at any point of a replay without recomputing the match.
Coordinates are SPADL (the acting team attacks +x), as in core/metrics.
"""

import math
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml

from core.contracts import MatchEvent
from core.metrics import positional
from core.metrics.events import PASSES, SHOTS, TOUCHES, Events, in_box, is_goal
from core.metrics.play import regains

CROSSES = {"cross", "corner_crossed", "freekick_crossed"}
Z95 = 1.96


@cache
def config() -> dict:
    return yaml.safe_load((Path(__file__).with_name("stat_groups.yaml")).read_text())


@dataclass(frozen=True)
class Contribution:
    index: int  # the event that changed the stat
    value: float  # added to the stat (counts: 1; xG: the shot's xG)
    numerator: int = 0  # rates: successes added
    denominator: int = 0  # rates: attempts added
    evidence: tuple[str, ...] = ()  # event ids behind it


@dataclass(frozen=True)
class Stat:
    name: str
    label: str
    definition: str
    unit: str  # "count", "share" (a rate, with a Wilson interval), "xG", "lines"
    sources: frozenset[str]  # event types it is counted from
    rate: bool = False  # value = numerator / denominator
    of: bool = False  # shown as "completed of attempted" (long passes, crosses)


STATS: dict[str, Stat] = {
    s.name: s
    for s in [
        Stat("goals", "Goals", "Shots he scored.", "count", frozenset(SHOTS)),
        Stat(
            "shots",
            "Shots",
            "Shots he took, free kicks included.",
            "count",
            frozenset(SHOTS),
        ),
        Stat(
            "chances_created",
            "Chances created",
            "Passes to a teammate who then shot, with no other pass in between.",
            "count",
            frozenset(PASSES | SHOTS),
        ),
        Stat(
            "assists",
            "Assists",
            "Chances created that were scored.",
            "count",
            frozenset(PASSES | SHOTS),
        ),
        Stat(
            "shots_on_target",
            "Shots on target",
            "Shots that scored or that the keeper saved.",
            "count",
            frozenset(SHOTS | {"keeper_save"}),
        ),
        Stat("xg", "xG", "Sum of the xG of his shots.", "xG", frozenset(SHOTS)),
        Stat(
            "touches_in_box",
            "Touches in the box",
            "Actions on the ball that started in the opponent's penalty area.",
            "count",
            frozenset(TOUCHES),
        ),
        Stat(
            "passes_completed",
            "Passes completed",
            "Passes that found a teammate (throw-ins not counted).",
            "count",
            frozenset(PASSES),
        ),
        Stat(
            "pass_pct",
            "Pass completion",
            "Completed passes divided by attempted passes.",
            "share",
            frozenset(PASSES),
            rate=True,
        ),
        Stat(
            "lines_broken",
            "Lines broken",
            "Defending lines his completed passes crossed going forward.",
            "lines",
            frozenset(PASSES),
        ),
        Stat(
            "recoveries",
            "Ball recoveries",
            "Times he won the ball back for his team in open play.",
            "count",
            frozenset(TOUCHES | {"tackle", "interception"}),
        ),
        Stat("tackles", "Tackles", "Tackles he made.", "count", frozenset({"tackle"})),
        Stat(
            "interceptions",
            "Interceptions",
            "Passes he intercepted.",
            "count",
            frozenset({"interception"}),
        ),
        Stat(
            "clearances",
            "Clearances",
            "Clearances he made.",
            "count",
            frozenset({"clearance"}),
        ),
        Stat(
            "long_passes",
            "Long passes",
            "Passes of at least long_pass_m metres: completed of attempted.",
            "count",
            frozenset(PASSES),
            of=True,
        ),
        Stat(
            "crosses",
            "Crosses",
            "Crosses, corners and free kicks into the box: completed of attempted.",
            "count",
            frozenset(CROSSES),
            of=True,
        ),
        Stat("saves", "Saves", "Shots he saved.", "count", frozenset({"keeper_save"})),
        Stat(
            "goals_conceded",
            "Goals conceded",
            "Goals against his team while he was on the pitch.",
            "count",
            frozenset(SHOTS),
        ),
        Stat(
            "xg_faced",
            "xG faced",
            "Sum of the xG of the opponent's shots while he was on the pitch.",
            "xG",
            frozenset(SHOTS),
        ),
    ]
}


def group_of(position: str) -> str:
    for name, g in config()["groups"].items():
        if position in g["positions"]:
            return name
    raise KeyError(f"no stat group for position {position!r}")


def card_stats(position: str, persona: str) -> list[str]:
    """The stats a persona sees for a player in this position."""
    g = config()["groups"][group_of(position)]
    return list(g["fan"]) + (list(g["analyst"]) if persona == "analyst" else [])


def on_pitch(e: MatchEvent, player_id: str) -> bool:
    return any(p.player_id == player_id for p in e.freeze_frame)


def last_pass_before(ev: Events, i: int) -> int | None:
    """The latest pass by the shooter's team in the shot's possession, with
    no other pass in between (dribbles and take-ons allowed)."""
    shot = ev.items[i]
    k = i - 1
    while k >= 0 and ev.items[k].possession_id == shot.possession_id:
        e = ev.items[k]
        if e.team_id == shot.team_id and e.type in PASSES:
            return k
        k -= 1
    return None


def contributions(
    ev: Events, player_id: str, team: str
) -> dict[str, list[Contribution]]:
    """Every stat's contributions for one player, in match order."""
    long_m = config()["long_pass_m"]
    out: dict[str, list[Contribution]] = {name: [] for name in STATS}

    def add(name, i, value=1.0, num=0, den=0, evidence=None):
        ids = evidence or (ev.items[i].event_id,)
        out[name].append(Contribution(i, value, num, den, tuple(ids)))

    items = ev.items
    for i, e in enumerate(items):
        mine = e.player_id == player_id
        if mine and e.type in SHOTS:
            add("shots", i)
            xg = float(e.qualifiers.get("xg", 0.0))
            add("xg", i, xg)
            if e.outcome == "success":
                add("goals", i)
            nxt = items[i + 1] if i + 1 < len(items) else None
            saved = (
                nxt is not None and nxt.type == "keeper_save" and nxt.team_id != team
            )
            if e.outcome == "success" or saved:
                ids = (e.event_id,) + ((nxt.event_id,) if saved else ())
                add("shots_on_target", i, evidence=ids)
        if e.type in SHOTS and e.team_id == team and not mine:
            k = last_pass_before(ev, i)
            if k is not None and items[k].player_id == player_id:
                ids = (items[k].event_id, e.event_id)
                add("chances_created", i, evidence=ids)
                if e.outcome == "success":
                    add("assists", i, evidence=ids)
        if mine and e.type in TOUCHES and in_box(e.start_x, e.start_y):
            add("touches_in_box", i)
        if mine and e.type in PASSES:
            done = e.outcome == "success"
            add("pass_pct", i, 0.0, int(done), 1)
            if done:
                add("passes_completed", i)
                lines = positional.lines_broken(ev, i).value
                if lines:
                    add("lines_broken", i, lines)
            if float(e.qualifiers.get("length_m", 0.0)) >= long_m:
                add("long_passes", i, float(done), int(done), 1)
        if mine and e.type in CROSSES:
            done = e.outcome == "success"
            add("crosses", i, float(done), int(done), 1)
        if mine and e.type == "tackle":
            add("tackles", i)
        if mine and e.type == "interception":
            add("interceptions", i)
        if mine and e.type == "clearance":
            add("clearances", i)
        if mine and e.type == "keeper_save":
            add("saves", i)
        against = (e.type in SHOTS and e.team_id != team) or (
            e.outcome == "owngoal" and e.team_id == team
        )
        if against and on_pitch(e, player_id):
            if is_goal(e):
                add("goals_conceded", i)
            if e.type in SHOTS:
                add("xg_faced", i, float(e.qualifiers.get("xg", 0.0)))
    index = {e.event_id: i for i, e in enumerate(items)}
    for won, _, _ in regains(ev, 0, team):
        if won.player_id == player_id:
            add("recoveries", index[won.event_id])
    out["recoveries"].sort(key=lambda c: c.index)
    return out


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float] | None:
    """Wilson score interval for k successes in n tries (95% by default)."""
    if n == 0:
        return None
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (max(0.0, centre - half), min(1.0, centre + half))


def total(stat: Stat, parts: list[Contribution]) -> dict:
    """The stat from its contributions: value, counts, interval, evidence."""
    num = sum(c.numerator for c in parts)
    den = sum(c.denominator for c in parts)
    if stat.rate:
        value = num / den if den else None
    else:
        value = round(sum(c.value for c in parts), 3)
    return {
        "value": value,
        "numerator": num if (stat.rate or stat.of) else None,
        "denominator": den if (stat.rate or stat.of) else None,
        "interval": wilson(num, den) if stat.rate else None,
        "evidence_event_ids": [i for c in parts for i in c.evidence],
    }


def snapshots(stat: Stat, parts: list[Contribution], t: list[float]) -> list[dict]:
    """The stat after each change, with the match second it changed (t)."""
    out = []
    for k in range(len(parts)):
        row = total(stat, parts[: k + 1])
        row.pop("evidence_event_ids")
        out.append({"t": t[parts[k].index], **row})
    return out
