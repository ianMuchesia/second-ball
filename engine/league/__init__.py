"""Fictional league: club style profiles loaded from engine/league/clubs/*.yaml."""

import re
from pathlib import Path
from typing import Annotated

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CLUBS_DIR = Path(__file__).parent / "clubs"
COMPETITION = "Second Ball League (fictional)"

SHAPE = re.compile(r"^\d(-\d){1,4}$")


def parse_shape(shape):
    """'4-3-3' -> [4, 3, 3]. Outfield lines, back to front, must sum to 10."""
    if not SHAPE.match(shape):
        raise ValueError(f"shape {shape!r} must look like '4-3-3'")
    lines = [int(n) for n in shape.split("-")]
    if sum(lines) != 10 or 0 in lines:
        raise ValueError(
            f"shape {shape!r} must have 10 outfield players and no empty line"
        )
    return lines


def mirror_role(role):
    """LB <-> RB, LCM <-> RCM, ... ; DM, ST, GK stay."""
    if role.startswith("L"):
        return "R" + role[1:]
    if role.startswith("R"):
        return "L" + role[1:]
    return role


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Tempo(Strict):
    passes_per_possession: Annotated[float, Field(ge=2, le=12)]
    seconds_per_action: Annotated[float, Field(ge=1.5, le=8)]


class Counterpress(Strict):
    probability: Annotated[float, Field(ge=0, le=1)]
    duration_s: Annotated[float, Field(ge=0, le=15)]


class Player(Strict):
    number: Annotated[int, Field(ge=1, le=99)]
    name: Annotated[str, Field(min_length=1)]
    role: str | None = None  # needed when the club writes its own shapes


# [depth, y]: depth 0 = back line, 1 = front line; y in metres, left touchline = 68.
Anchor = tuple[
    Annotated[float, Field(ge=0, le=1)], Annotated[float, Field(ge=0, le=68)]
]


class SideShapes(Strict):
    left: dict[str, Anchor]
    centre: dict[str, Anchor] | None = None  # default: halfway between left and right
    # right is always the mirror of left


class TransitionShapes(Strict):
    left: dict[str, Anchor] | None = None
    centre: dict[str, Anchor] | None = None
    right: dict[str, Anchor] | None = None


class Shapes(Strict):
    in_possession: SideShapes
    out_of_possession: SideShapes
    transition: TransitionShapes | None = None  # default: halfway between in and out


class OnRegain(Strict):
    channel_probability: Annotated[
        float, Field(ge=0, le=1)
    ]  # first pass behind the ball-side FB
    runners: Annotated[
        int, Field(ge=1, le=3)
    ]  # most advanced players who run in behind


class BuildUp(Strict):
    short_until_x: Annotated[float, Field(ge=0, le=60)]  # keep it short this far out
    flank_bias: Annotated[float, Field(ge=0, le=1)]  # then prefer the ball-side flank


class ClubProfile(Strict):
    id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]
    name: str
    stadium: str
    style: str
    formation: str
    in_possession_shape: str
    target_ppda: Annotated[float, Field(ge=4, le=20)]
    block_height: Annotated[float, Field(ge=25, le=55)]
    late_lead_block_drop: Annotated[float, Field(ge=0, le=20)]
    directness: Annotated[float, Field(ge=0, le=1)]
    width: Annotated[float, Field(ge=0, le=1)]
    tempo: Tempo
    counterpress: Counterpress
    players: Annotated[list[Player], Field(min_length=11, max_length=11)]
    shapes: Shapes | None = None
    build_up: BuildUp | None = None
    on_regain: OnRegain | None = None

    @field_validator("formation", "in_possession_shape")
    @classmethod
    def valid_shape(cls, shape):
        parse_shape(shape)
        return shape

    @field_validator("players")
    @classmethod
    def unique_numbers(cls, players):
        if len({p.number for p in players}) != len(players):
            raise ValueError("players have duplicate numbers")
        return players

    @model_validator(mode="after")
    def shapes_match_roles(self):
        if self.shapes is None:
            return self
        if self.players[0].role != "GK":
            raise ValueError("with shapes, the first player must have role GK")
        roles = [p.role for p in self.players[1:]]
        if None in roles or len(set(roles)) != 10:
            raise ValueError("with shapes, every outfield player needs a unique role")
        expected = set(roles)
        if {mirror_role(r) for r in expected} != expected:
            raise ValueError(
                "roles must mirror (LB<->RB, ...) so right can mirror left"
            )
        shapes = [
            self.shapes.in_possession.left,
            self.shapes.in_possession.centre,
            self.shapes.out_of_possession.left,
            self.shapes.out_of_possession.centre,
        ]
        if self.shapes.transition:
            t = self.shapes.transition
            shapes += [t.left, t.centre, t.right]
        for shape in shapes:
            if shape is not None and set(shape) != expected:
                raise ValueError(
                    f"shape roles {sorted(shape)} != player roles {sorted(expected)}"
                )
        return self

    def player_id(self, index):
        return f"{self.id}-{self.players[index].number}"


def load_club(path):
    return ClubProfile.model_validate(yaml.safe_load(Path(path).read_text()))


def load_league(clubs_dir=CLUBS_DIR):
    """All clubs by id, sorted. Files starting with '_' (templates) are skipped."""
    clubs = [
        load_club(p)
        for p in sorted(Path(clubs_dir).glob("*.yaml"))
        if not p.name.startswith("_")
    ]
    return {club.id: club for club in clubs}
