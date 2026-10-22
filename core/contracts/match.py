from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from core.contracts.common import Contract, NonEmptyStr, UnitInterval

Weather = Literal["dry", "rain", "wind", "heat"]
# scenario = scripted beats (must be labelled as such in the UI);
# free_simulation = the engine alone.
MatchMode = Literal["scenario", "free_simulation"]


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

    @model_validator(mode="after")
    def teams_differ(self):
        if self.home_team == self.away_team:
            raise ValueError("home_team and away_team must differ")
        return self
