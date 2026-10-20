from typing import Annotated

from pydantic import Field

from core.contracts.common import Clock, Contract, MetricValue, Part


class Score(Part):
    home: Annotated[int, Field(ge=0)]
    away: Annotated[int, Field(ge=0)]


class MatchState(Contract):
    score: Score
    clock: Clock
    # metrics[team_id][metric_name]
    metrics: dict[str, dict[str, MetricValue]]
