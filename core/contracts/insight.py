from core.contracts.common import Contract, EvidenceEventIds, NonEmptyStr, UnitInterval


class Insight(Contract):
    claim: NonEmptyStr
    mechanism: NonEmptyStr
    evidence_event_ids: EvidenceEventIds
    confidence: UnitInterval
