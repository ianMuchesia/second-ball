"""The evidence behind a moment, in two layers, computed from the events:

- the move: the smallest run of events that proves the claim. For a goal, a
  chance or a red card: the possession that ended in it, plus the defensive
  action that won the ball (the regain), if it was won in open play.
- the numbers: each metric the moment quotes, summarised (value, how many
  events it was computed over, from when to when). Their events are NOT the
  move: a 10-minute window is context, not proof of one goal.
"""

from core.contracts import MatchEvent
from core.metrics.events import RESTARTS

# Moments about one action: their move is the possession that led to it.
MOVE_KINDS = {"goal", "big_chance", "red_card_impact"}
# Actions that win the ball from the other team (the regain).
WINS_BALL = {"tackle", "interception", "keeper_save", "keeper_claim", "keeper_pick_up"}


def move(events: list[MatchEvent], index: dict[str, int], end_id: str) -> dict:
    """The possession ending at end_id, with the event that won the ball.

    The regain is the scoring team's tackle or interception that ended the
    other team's possession (it belongs to that possession in the feed); else
    the possession's first touch, if it did not start from a restart; else none.
    """
    i = index[end_id]
    pid = events[i].possession_id
    k = i
    while k > 0 and events[k - 1].possession_id == pid:
        k -= 1
    owner = events[k].team_id
    regain = None
    before = events[k - 1] if k > 0 else None
    if before and before.team_id == owner and before.type in WINS_BALL:
        k -= 1
        regain = before.event_id
    elif events[k].type not in RESTARTS and before and before.team_id != owner:
        regain = events[k].event_id
    chain = events[k : i + 1]
    return {
        "ids": [e.event_id for e in chain],
        "regain_id": regain,
        "players": list(dict.fromkeys(e.player_id for e in chain)),
        "team": owner,
    }


def evidence_of(moment: dict, events: list[MatchEvent], index: dict[str, int]) -> dict:
    """The move behind a moment: the possession for one-action moments, else
    the moment's own evidence events in match order."""
    ids = [i for i in moment["evidence_event_ids"] if i in index]
    if moment["kind"] in MOVE_KINDS and ids:
        end = max(ids, key=index.__getitem__)
        return move(events, index, end)
    ids.sort(key=index.__getitem__)
    return {
        "ids": ids,
        "regain_id": None,
        "players": list(dict.fromkeys(events[index[i]].player_id for i in ids)),
        "team": moment.get("team"),
    }


def numbers(moment: dict, index: dict[str, int], t: dict[str, float]) -> list[dict]:
    """Each metric the moment quotes: value, event count and the time span
    its events cover (its window, as it was really computed)."""
    out = []
    for when in ("before", "after"):
        for name, mv in moment[f"metrics_{when}"].items():
            ids = [i for i in mv["evidence_event_ids"] if i in index]
            times = [t[i] for i in ids]
            out.append(
                {
                    "metric": name,
                    "when": when,
                    "value": mv["value"],
                    "events": len(ids),
                    "from_t": min(times) if times else None,
                    "to_t": max(times) if times else None,
                }
            )
    return out
