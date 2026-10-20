from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, field_validator

from core.contracts.common import Clock, Contract, EvidenceEventIds, NonEmptyStr, Part

RiskTier = Literal["low", "medium", "high"]
OverlayStatus = Literal["pending", "approved", "aired", "expired"]


class OverlayTime(Part):
    match: Clock
    wall: AwareDatetime


class Overlay(Contract):
    overlay_id: NonEmptyStr
    match_id: NonEmptyStr
    kind: NonEmptyStr
    slot: NonEmptyStr
    t_in: OverlayTime
    duration_ms: Annotated[int, Field(gt=0)]
    priority: Annotated[int, Field(ge=0)]
    risk_tier: RiskTier
    # text[language], e.g. {"en": "...", "sw": "..."}
    text: dict[str, NonEmptyStr]
    values: dict[str, float]
    evidence_event_ids: EvidenceEventIds
    status: OverlayStatus

    @field_validator("text")
    @classmethod
    def english_required(cls, text):
        if "en" not in text:
            raise ValueError("text must include 'en'")
        return text
