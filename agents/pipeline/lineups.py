"""Team-sheet words: how a position is said, and which positions a word may
describe (the Verifier checks "left-back Lindqvane" against the sheet)."""

import re

from core.contracts import LineupPlayer

SAID = {
    "GK": "goalkeeper",
    "RB": "right-back",
    "LB": "left-back",
    "RCB": "right centre-back",
    "CB": "centre-back",
    "LCB": "left centre-back",
    "RWB": "right wing-back",
    "LWB": "left wing-back",
    "DM": "defensive midfielder",
    "RCM": "central midfielder",
    "CM": "central midfielder",
    "LCM": "central midfielder",
    "RM": "right midfielder",
    "LM": "left midfielder",
    "AM": "attacking midfielder",
    "RW": "right winger",
    "LW": "left winger",
    "ST": "striker",
}
CB = {"RCB", "CB", "LCB"}
FULL = {"RB", "LB", "RWB", "LWB"}
MIDS = {"DM", "RCM", "CM", "LCM", "RM", "LM", "AM"}
# Words a line may use -> the positions they can describe.
CLAIMS = {
    "goalkeeper": {"GK"},
    "keeper": {"GK"},
    "left-back": {"LB", "LWB"},
    "left back": {"LB", "LWB"},
    "right-back": {"RB", "RWB"},
    "right back": {"RB", "RWB"},
    "full-back": FULL,
    "fullback": FULL,
    "left wing-back": {"LWB"},
    "right wing-back": {"RWB"},
    "wing-back": {"RWB", "LWB"},
    "left centre-back": {"LCB"},
    "right centre-back": {"RCB"},
    "centre-back": CB,
    "center-back": CB,
    "central defender": CB,
    "defender": CB | FULL,
    "defensive midfielder": {"DM"},
    "holding midfielder": {"DM"},
    "central midfielder": {"RCM", "CM", "LCM"},
    "attacking midfielder": {"AM", "RCM", "LCM"},
    "midfielder": MIDS,
    "left winger": {"LW", "LM"},
    "right winger": {"RW", "RM"},
    "winger": {"RW", "LW", "RM", "LM"},
    "striker": {"ST"},
    "centre-forward": {"ST"},
    "forward": {"ST", "RW", "LW"},
}
# Style words (contracts.PlayingStyle) must match the player's own style.
STYLE_WORDS = [
    "sweeper keeper",
    "ball-playing centre-back",
    "stopper",
    "inverted full-back",
    "overlapping full-back",
    "deep-lying playmaker",
    "box-to-box midfielder",
    "box-to-box",
    "inverted winger",
    "touchline winger",
    "poacher",
    "target man",
    "false 9",
    "false nine",
    "creative 9",
    "second striker",
]
STYLE_OF = {"box-to-box": "box-to-box midfielder", "false nine": "false 9"}


def said(p: LineupPlayer) -> str:
    return SAID[p.position]


def surname(p: LineupPlayer) -> str:
    return p.name.split()[-1]


def name_pattern(p: LineupPlayer) -> str:
    return rf"(?:{re.escape(p.name)}|{re.escape(surname(p))})"


def describe(p: LineupPlayer, team: str) -> str:
    """'Riverside, left centre-back, ball-playing centre-back, number 5'."""
    parts = [team, said(p)]
    if p.style:
        parts.append(p.style)
    parts.append(f"number {p.shirt_number}")
    return ", ".join(parts)
