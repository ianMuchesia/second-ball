"""Fictional league: club style profiles loaded from engine/league/clubs/*.yaml."""

import re
from pathlib import Path
from typing import Annotated

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.contracts.match import PlayingStyle

CLUBS_DIR = Path(__file__).parent / "clubs"
COMPETITION = "Second Ball League (fictional)"

SHAPE = re.compile(r"^\d(-\d){1,4}$")


def parse_shape(shape, outfield=10):
    """'4-3-3' -> [4, 3, 3]. Outfield lines, back to front, must sum to `outfield`."""
    if not SHAPE.match(shape):
        raise ValueError(f"shape {shape!r} must look like '4-3-3'")
    lines = [int(n) for n in shape.split("-")]
    if sum(lines) != outfield or 0 in lines:
        raise ValueError(
            f"shape {shape!r} must have {outfield} outfield players and no empty line"
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
    style: PlayingStyle | None = (
        None  # how he plays it (team sheet); TUNABLE, owner Ian
    )


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


class ShapeOverride(Strict):
    """A formation used in one situation. `order` lists the roles back to front,
    right to left within a line (clubs with roles); generic clubs omit it.
    For shape_after_red_card, list all 10 roles: the one missing is skipped."""

    formation: str
    order: list[str] | None = None


class OnRegain(Strict):
    channel_probability: Annotated[
        float, Field(ge=0, le=1)
    ]  # first pass behind the ball-side FB
    runners: Annotated[
        int, Field(ge=1, le=3)
    ]  # most advanced players who run in behind


class SetPieces(Strict):
    threat: Annotated[float, Field(ge=0, le=1)] = 0.5  # delivery + aerial quality
    foul_drawing: Annotated[float, Field(ge=0, le=1)] = (
        0.3  # wins fouls in the final third
    )
    corner_seeking: Annotated[float, Field(ge=0, le=1)] = (
        0.3  # crosses / shots that win corners
    )


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
    strength: Annotated[float, Field(ge=0, le=1)]  # 0-1; who is the stronger side
    shape_when_protecting_lead: ShapeOverride | None = None  # without the ball
    shape_when_chasing: ShapeOverride | None = None  # with the ball
    shape_after_red_card: ShapeOverride | None = None  # 9 outfield players
    shapes: Shapes | None = None
    build_up: BuildUp | None = None
    on_regain: OnRegain | None = None
    set_pieces: SetPieces = SetPieces()

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

    @model_validator(mode="after")
    def overrides_are_valid(self):
        roles = {p.role for p in self.players[1:]} if self.shapes else None
        for name, outfield in (
            ("shape_when_protecting_lead", 10),
            ("shape_when_chasing", 10),
            ("shape_after_red_card", 9),
        ):
            ov = getattr(self, name)
            if ov is None:
                continue
            parse_shape(ov.formation, outfield)
            if roles is None and ov.order is not None:
                raise ValueError(f"{name}: order is only for clubs with player roles")
            if roles is not None and set(ov.order or []) != roles:
                raise ValueError(f"{name}: order must list every outfield role once")
            if ov.order is not None and len(ov.order) != len(set(ov.order)):
                raise ValueError(f"{name}: order has a duplicate role")
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
