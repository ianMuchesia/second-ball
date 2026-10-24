"""Events for people: absolute pitch coordinates and one plain sentence.

Event coordinates are from the acting team's view (SPADL: it attacks +x).
The screen draws one pitch, so away-team events are turned round: home
attacks left to right."""

from agents.pipeline.facts import TEAM_NAMES
from agents.pipeline.lineups import SAID
from core.contracts import Match, MatchEvent
from core.metrics.events import SHOTS

LENGTH, WIDTH = 105.0, 68.0
VERB = {
    "pass": "passes",
    "cross": "crosses",
    "throw_in": "takes a throw-in",
    "freekick_crossed": "crosses a free kick",
    "freekick_short": "takes a short free kick",
    "corner_crossed": "crosses a corner",
    "corner_short": "takes a short corner",
    "take_on": "takes on his man",
    "foul": "fouls",
    "tackle": "tackles",
    "interception": "intercepts",
    "shot": "shoots",
    "shot_penalty": "takes a penalty",
    "shot_freekick": "shoots from a free kick",
    "keeper_save": "saves",
    "keeper_claim": "claims the ball",
    "keeper_punch": "punches clear",
    "keeper_pick_up": "picks up the ball",
    "clearance": "clears",
    "bad_touch": "loses control",
    "non_action": "",
    "dribble": "carries the ball",
    "goalkick": "takes a goal kick",
}


def team_name(team_id: str) -> str:
    return TEAM_NAMES.get(team_id, team_id.replace("_", " ").title())


def flip(team_id: str, match: Match) -> bool:
    return team_id == match.away_team


def point(x: float, y: float, turn: bool) -> list[float]:
    return (
        [round(LENGTH - x, 2), round(WIDTH - y, 2)]
        if turn
        else [round(x, 2), round(y, 2)]
    )


def absolute(e: MatchEvent, match: Match, t: float | None = None) -> dict:
    """The event for the screen: absolute coordinates (home attacks +x)."""
    turn = flip(e.team_id, match)
    return {
        "event_id": e.event_id,
        "possession_id": e.possession_id,
        "t": t,
        "period": e.period,
        "minute": e.minute,
        "second": e.second,
        "team_id": e.team_id,
        "player_id": e.player_id,
        "type": e.type,
        "outcome": e.outcome,
        "start": point(e.start_x, e.start_y, turn),
        "end": point(e.end_x, e.end_y, turn),
        "xg": e.qualifiers.get("xg"),
        "ball_speed_kmh": e.ball_speed_kmh,  # the 3D ball's flight time
        "freeze_frame": [
            {
                "player_id": p.player_id,
                "team_id": p.team_id,
                "xy": point(p.x, p.y, turn),
                "facing_deg": round((p.facing_deg + (180 if turn else 0)) % 360, 1),
            }
            for p in e.freeze_frame
        ],
    }


def describe_event(e: MatchEvent, match: Match) -> str:
    """'63:09 Ilya Stonebridge (Riverside, left centre-back) fouls: red card.'"""
    sheet = {p.player_id: p for p in match.lineups}
    p = sheet.get(e.player_id)
    who = (
        f"{p.name} ({team_name(e.team_id)}, {SAID[p.position]})"
        if p
        else f"{team_name(e.team_id)} {e.player_id.rsplit('-', 1)[-1]}"
    )
    verb = VERB.get(e.type, e.type.replace("_", " "))
    if e.type in SHOTS:
        how = {"success": ": goal", "fail": ": no goal", "owngoal": ": own goal"}
        tail = how.get(e.outcome, "")
        if e.qualifiers.get("xg") is not None:
            tail += f" (xG {float(e.qualifiers['xg']):.2f})"
    elif e.outcome in ("yellow_card", "red_card"):
        tail = f": {e.outcome.replace('_', ' ')}"
    elif e.outcome == "fail":
        tail = ", unsuccessfully"
    elif e.outcome == "offside":
        tail = ": offside"
    else:
        tail = ""
    return f"{e.minute:02d}:{e.second:02d} {who} {verb}{tail}.".replace("  ", " ")
