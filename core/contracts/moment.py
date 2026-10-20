from core.contracts.common import (
    Contract,
    EvidenceEventIds,
    MetricValue,
    NonEmptyStr,
    UnitInterval,
)


class Moment(Contract):
    moment_id: NonEmptyStr
    kind: NonEmptyStr
    importance: UnitInterval
    metrics_before: dict[str, MetricValue]
    metrics_after: dict[str, MetricValue]
    evidence_event_ids: EvidenceEventIds
