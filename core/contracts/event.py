from collections import Counter
from typing import Annotated, Literal

from pydantic import Field, model_validator

from core.contracts.common import Contract, NonEmptyStr, Part, X, Y

# SPADL action types, results and body parts (socceraction).
ActionType = Literal[
    "pass",
    "cross",
    "throw_in",
    "freekick_crossed",
    "freekick_short",
    "corner_crossed",
    "corner_short",
    "take_on",
    "foul",
    "tackle",
    "interception",
    "shot",
    "shot_penalty",
    "shot_freekick",
    "keeper_save",
    "keeper_claim",
    "keeper_punch",
    "keeper_pick_up",
    "clearance",
    "bad_touch",
    "non_action",
    "dribble",
    "goalkick",
]
Outcome = Literal["success", "fail", "offside", "owngoal", "yellow_card", "red_card"]
BodyPart = Literal["foot", "foot_left", "foot_right", "head", "other"]

MAX_PLAYERS_PER_TEAM = 11


class PlayerPosition(Part):
    """Facing angle in degrees: 0 points along +x, 90 along +y (anticlockwise)."""

    player_id: NonEmptyStr
    team_id: NonEmptyStr
    x: X
    y: Y
    facing_deg: Annotated[float, Field(ge=0, lt=360)]


class MatchEvent(Contract):
    """SPADL convention: coordinates are from the acting team's view, so it attacks
    towards x=105 and its own goal is at x=0."""

    event_id: NonEmptyStr
    match_id: NonEmptyStr
    possession_id: NonEmptyStr
    period: Annotated[int, Field(ge=1, le=5)]
    minute: Annotated[int, Field(ge=0)]
    second: Annotated[int, Field(ge=0, le=59)]
    team_id: NonEmptyStr
    player_id: NonEmptyStr
    type: ActionType
    outcome: Outcome
    body_part: BodyPart
    start_x: X
    start_y: Y
    end_x: X
    end_y: Y
    under_pressure: bool
    ball_speed_kmh: Annotated[float, Field(ge=0)] | None = None
    qualifiers: dict[str, str | int | float | bool] = Field(default_factory=dict)
    # Up to 22: sent-off players are simply absent.
    freeze_frame: Annotated[list[PlayerPosition], Field(min_length=1, max_length=22)]

    @model_validator(mode="after")
    def freeze_frame_is_consistent(self):
        ids = [p.player_id for p in self.freeze_frame]
        if len(ids) != len(set(ids)):
            raise ValueError("freeze_frame has duplicate player_id")
        per_team = Counter(p.team_id for p in self.freeze_frame)
        if len(per_team) > 2:
            raise ValueError("freeze_frame has more than two teams")
        if any(n > MAX_PLAYERS_PER_TEAM for n in per_team.values()):
            raise ValueError("freeze_frame has more than 11 players for one team")
        return self
