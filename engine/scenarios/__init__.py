"""Scenario mode: a seed plus scripted "beats". Between beats the normal engine runs.

A beat's minute window says when it happens. Scripted events carry the
qualifier `scenario_beat` so they can always be told apart from free play.
In scenario mode the engine scores no goals and shows no red cards of its own:
only the script does, so the final score is exactly the scripted one.
"""

from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from core.contracts.match import Weather

SCENARIOS_DIR = Path(__file__).parent
Minute = Annotated[int, Field(ge=0, le=95)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Beat(Strict):
    id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]
    minute: tuple[Minute, Minute]
    # counter_goal / counter_chance: `team` wins the ball and counters behind
    #   the opponent's `behind` full-back, then scores / misses.
    # red_card_last_man: `team` concedes the counter and its `role` player is
    #   sent off for a last-man foul.
    # block_drop: `team` defends `extra_drop_m` deeper during the window.
    action: Literal["counter_goal", "counter_chance", "red_card_last_man", "block_drop"]
    team: Literal["home", "away"]
    behind: Literal["left", "right"] = "left"
    role: str | None = None
    extra_drop_m: Annotated[float, Field(ge=0, le=20)] = 0.0
    min_xg: Annotated[float, Field(ge=0, le=1)] | None = None  # raise the shot's xG

    @model_validator(mode="after")
    def window_in_order(self):
        if self.minute[0] > self.minute[1]:
            raise ValueError("minute window must be [start, end]")
        if self.action == "red_card_last_man" and not self.role:
            raise ValueError("red_card_last_man needs the role of the player sent off")
        return self


class ExpectedMoment(Strict):
    kind: Annotated[str, Field(min_length=1)]
    team: Literal["home", "away"] | None  # None = match-wide
    minute: tuple[Minute, Minute]
    note: str = ""


class Scenario(Strict):
    id: str
    home: str
    away: str
    seed: Annotated[int, Field(ge=0)]
    weather: Weather
    kickoff: AwareDatetime
    beats: list[Beat]
    expected_moments: list[ExpectedMoment]

    def scripted(self):
        """Beats that play a sequence once (not modifiers like block_drop)."""
        return [b for b in self.beats if b.action != "block_drop"]


def load_scenario(name, scenarios_dir=SCENARIOS_DIR):
    path = Path(scenarios_dir) / f"{name}.yaml"
    return Scenario.model_validate(yaml.safe_load(path.read_text()))


def expected_moments(scenario, match):
    """The answer key for evals: what a moment detector should find in this match."""
    team_id = {"home": match.home_team, "away": match.away_team, None: None}
    return {
        "scenario": scenario.id,
        "match_id": match.match_id,
        "mode": match.mode,
        "moments": [
            {
                "kind": m.kind,
                "team": team_id[m.team],
                "minute": list(m.minute),
                **({"note": m.note} if m.note else {}),
            }
            for m in scenario.expected_moments
        ],
    }
