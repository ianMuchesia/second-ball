"""Fictional league: club style profiles loaded from engine/league/clubs/*.yaml."""

import re
from pathlib import Path
from typing import Annotated

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

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
