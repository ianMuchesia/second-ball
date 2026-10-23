from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from core.contracts.common import Contract, NonEmptyStr, Part, UnitInterval

Weather = Literal["dry", "rain", "wind", "heat"]
# scenario = scripted beats (must be labelled as such in the UI);
# free_simulation = the engine alone.
MatchMode = Literal["scenario", "free_simulation"]


# Where a player lines up (the team sheet). Sided centre-backs and
# midfielders keep their side: "left centre-back" is a fact on the sheet.
Position = Literal[
    "GK",
    "RB", "RCB", "CB", "LCB", "LB", "RWB", "LWB",
    "DM", "RCM", "CM", "LCM", "RM", "LM", "AM",
    "RW", "LW", "ST",
]  # fmt: skip
# How a player plays the position (Ian's football vocabulary). Optional: a
# team sheet gives positions; a style is the club's own description.
PlayingStyle = Literal[
    "sweeper keeper",
    "ball-playing centre-back",
    "stopper",
    "inverted full-back",
    "overlapping full-back",
    "wing-back",
    "deep-lying playmaker",
    "holding midfielder",
    "box-to-box midfielder",
    "attacking midfielder",
    "inverted winger",
    "touchline winger",
    "poacher",
    "target man",
    "false 9",
    "creative 9",
    "second striker",
]


class LineupPlayer(Part):
    """One player on the published team sheet (public before kick-off)."""

    player_id: NonEmptyStr  # as in MatchEvent.player_id
    team_id: NonEmptyStr
    name: NonEmptyStr
    shirt_number: Annotated[int, Field(ge=1, le=99)]
    position: Position
    style: PlayingStyle | None = None
    starting: bool = True  # False: on the bench


class Match(Contract):
    match_id: NonEmptyStr
    home_team: NonEmptyStr
    away_team: NonEmptyStr
    venue: NonEmptyStr
    kickoff: AwareDatetime
    competition: NonEmptyStr
    seed: Annotated[int, Field(ge=0)]
    weather: Weather
    mode: MatchMode
    # Public pre-match ratings (0-1), like a published league rating: a fact a
    # broadcaster has before kick-off, not an in-match engine internal.
    home_strength: UnitInterval
    away_strength: UnitInterval
    # Team sheets: public before kick-off, like the ratings. Empty for
    # matches recorded before lineups existed.
    lineups: list[LineupPlayer] = Field(default_factory=list)

    @model_validator(mode="after")
    def teams_differ(self):
        if self.home_team == self.away_team:
            raise ValueError("home_team and away_team must differ")
        return self

    @model_validator(mode="after")
    def lineups_fit(self):
        teams = {self.home_team, self.away_team}
        if any(p.team_id not in teams for p in self.lineups):
            raise ValueError("lineup player for a team not in this match")
        ids = [p.player_id for p in self.lineups]
        if len(ids) != len(set(ids)):
            raise ValueError("lineup has duplicate player_id")
        for team in teams:
            shirts = [p.shirt_number for p in self.lineups if p.team_id == team]
            if len(shirts) != len(set(shirts)):
                raise ValueError(f"lineup for {team} has duplicate shirt numbers")
            if sum(p.starting for p in self.lineups if p.team_id == team) > 11:
                raise ValueError(f"lineup for {team} starts more than 11")
        return self
