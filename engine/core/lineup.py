"""Team sheets: a club's starting XI as public LineupPlayers.

Positions come from the club's roles when it writes its own shapes (LCB,
DM, ...), otherwise from its formation: each line, right to left, gets the
positions a broadcaster would print (a back four is RB, RCB, LCB, LB).
"""

from core.contracts.match import LineupPlayer
from engine.core.shapes import parse_shape

ROLE_POSITION = {"GK": "GK", "ST": "ST"}  # engine role -> position, when not equal

BACK = {
    3: ["RCB", "CB", "LCB"],
    4: ["RB", "RCB", "LCB", "LB"],
    5: ["RWB", "RCB", "CB", "LCB", "LWB"],
}
FRONT = {1: ["ST"], 2: ["ST", "ST"], 3: ["RW", "ST", "LW"]}


def middle(n: int, deeper: bool, only: bool, back_three: bool) -> list[str]:
    """A midfield line, right to left. `deeper`: the lower of two lines."""
    if n == 4:
        return (
            ["RWB", "RCM", "LCM", "LWB"] if back_three else ["RM", "RCM", "LCM", "LM"]
        )
    if n == 5:
        return ["RM", "RCM", "CM", "LCM", "LM"]
    if only:
        return {1: ["CM"], 2: ["RCM", "LCM"], 3: ["RCM", "CM", "LCM"]}[n]
    if deeper:
        return {1: ["DM"], 2: ["DM", "DM"], 3: ["RCM", "DM", "LCM"]}[n]
    return {1: ["AM"], 2: ["AM", "AM"], 3: ["RW", "AM", "LW"]}[n]


def formation_positions(formation: str) -> list[str]:
    lines = parse_shape(formation)
    out = []
    mids = lines[1:-1]
    for i, n in enumerate(lines):
        if i == 0:
            out += BACK[n]
        elif i == len(lines) - 1:
            out += FRONT[n]
        else:
            k = i - 1
            out += middle(
                n,
                deeper=k == 0,
                only=len(mids) == 1,
                back_three=lines[0] == 3,
            )
    return out


def lineup(profile) -> list[LineupPlayer]:
    players = profile.players
    if all(p.role for p in players):
        positions = [ROLE_POSITION.get(p.role, p.role) for p in players]
    else:
        positions = ["GK", *formation_positions(profile.formation)]
    return [
        LineupPlayer(
            player_id=profile.player_id(i),
            team_id=profile.id,
            name=p.name,
            shirt_number=p.number,
            position=pos,
            style=p.style,
            starting=True,
        )
        for i, (p, pos) in enumerate(zip(players, positions, strict=True))
    ]
