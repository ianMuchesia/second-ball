from core.contracts.common import SCHEMA_VERSION, Clock, MetricValue
from core.contracts.event import MatchEvent, PlayerPosition
from core.contracts.insight import Insight
from core.contracts.match import LineupPlayer, Match
from core.contracts.moment import Moment
from core.contracts.overlay import Overlay, OverlayTime
from core.contracts.state import MatchState, Score

# Top-level contracts; exported to docs/schemas/ and web/src/types/.
CONTRACTS = [Match, MatchEvent, MatchState, Moment, Insight, Overlay]

__all__ = [
    "CONTRACTS",
    "SCHEMA_VERSION",
    "Clock",
    "Insight",
    "LineupPlayer",
    "Match",
    "MatchEvent",
    "MatchState",
    "MetricValue",
    "Moment",
    "Overlay",
    "OverlayTime",
    "PlayerPosition",
    "Score",
]
