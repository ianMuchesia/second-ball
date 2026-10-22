from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 1

PITCH_LENGTH_M = 105.0
PITCH_WIDTH_M = 68.0

NonEmptyStr = Annotated[str, Field(min_length=1)]
X = Annotated[float, Field(ge=0, le=PITCH_LENGTH_M)]
Y = Annotated[float, Field(ge=0, le=PITCH_WIDTH_M)]
UnitInterval = Annotated[float, Field(ge=0, le=1)]

# No number without evidence: every list of evidence ids must be non-empty.
EvidenceEventIds = Annotated[list[NonEmptyStr], Field(min_length=1)]


class Contract(BaseModel):
    # Defaulted fields are always present in output, so the exported schema requires them.
    model_config = ConfigDict(
        extra="forbid", json_schema_serialization_defaults_required=True
    )

    schema_version: Literal[1] = SCHEMA_VERSION


class Part(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Clock(Part):
    period: Annotated[int, Field(ge=1, le=5)]
    minute: Annotated[int, Field(ge=0)]
    second: Annotated[int, Field(ge=0, le=59)]


class MetricValue(Part):
    value: float
    evidence_event_ids: EvidenceEventIds
    # For rates (value = numerator / denominator): the raw counts, so intervals
    # (e.g. Wilson) can be computed later. None for non-rates.
    numerator: float | None = None
    denominator: float | None = None
