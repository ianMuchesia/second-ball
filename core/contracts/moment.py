from core.contracts.common import (
    Clock,
    Contract,
    EvidenceEventIds,
    MetricValue,
    NonEmptyStr,
    UnitInterval,
)


class Moment(Contract):
    moment_id: NonEmptyStr
    kind: NonEmptyStr
    team: NonEmptyStr | None  # None = match-wide
    clock: Clock  # when it fired
    importance: UnitInterval
    metrics_before: dict[str, MetricValue]
    metrics_after: dict[str, MetricValue]
    evidence_event_ids: EvidenceEventIds
