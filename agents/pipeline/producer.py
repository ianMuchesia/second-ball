"""Producer (code): what airs, when; stale lines are dropped.

- Stat cards and recaps air at once.
- A narrative line must air within 8 s of its moment or it expires.
- At most one narrative per 45 s; when several wait, the most important
  first (then the oldest).
- High-risk lines (injuries, referee) wait as `pending` until a human
  approves; low/medium risk lines are `approved` straight away.
- Status: pending -> approved -> aired, or expired.

Times are MATCH seconds (elapsed). The 8 s and 45 s are viewer seconds, so
they scale with replay speed: at 10x, a line has 80 match seconds to air.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from agents.pipeline.models import MatchContext
from agents.pipeline.prompts import KIND_WORDS
from core.contracts import Moment, Overlay
from core.contracts.overlay import OverlayTime

INSTANT = {"stat_card", "recap"}  # slots that air as soon as they are ready
FRESH_S = 8.0
NARRATIVE_GAP_S = 45.0


@dataclass
class Slot:
    overlay: Overlay
    moment_t: float  # match seconds when the moment happened
    importance: float


@dataclass
class Producer:
    speed: float = 1.0
    queue: list[Slot] = field(default_factory=list)
    aired: list[Overlay] = field(default_factory=list)
    expired: list[Overlay] = field(default_factory=list)
    last_narrative_t: float | None = None

    @property
    def fresh_s(self) -> float:
        return FRESH_S * self.speed

    @property
    def gap_s(self) -> float:
        return NARRATIVE_GAP_S * self.speed

    def offer(self, overlay: Overlay, moment_t: float, importance: float, now: float):
        """A finished overlay (narrative or stat card). Returns what aired now."""
        if overlay.slot in INSTANT:
            return [self.air(overlay)]
        status = "pending" if overlay.risk_tier == "high" else "approved"
        self.queue.append(
            Slot(overlay.model_copy(update={"status": status}), moment_t, importance)
        )
        return self.tick(now)

    def approve(self, overlay_id: str, now: float):
        """A human approved a high-risk line."""
        for s in self.queue:
            if s.overlay.overlay_id == overlay_id:
                s.overlay = s.overlay.model_copy(update={"status": "approved"})
        return self.tick(now)

    def tick(self, now: float) -> list[Overlay]:
        """Expire stale lines; air the best approved narrative if the gap allows."""
        for s in [s for s in self.queue if now - s.moment_t > self.fresh_s]:
            self.queue.remove(s)
            self.expired.append(s.overlay.model_copy(update={"status": "expired"}))
        if (
            self.last_narrative_t is not None
            and now - self.last_narrative_t < self.gap_s
        ):
            return []
        ready = [s for s in self.queue if s.overlay.status == "approved"]
        if not ready:
            return []
        best = max(ready, key=lambda s: (s.importance, -s.moment_t))
        self.queue.remove(best)
        self.last_narrative_t = now
        return [self.air(best.overlay)]

    def air(self, overlay: Overlay) -> Overlay:
        out = overlay.model_copy(update={"status": "aired"})
        self.aired.append(out)
        return out


def stat_card(moment: Moment, context: MatchContext) -> Overlay:
    """An instant card from code values only (no model): kind, team, numbers."""
    team = context.team_names.get(moment.team or "", "Match")
    values = {k: v.value for k, v in moment.metrics_after.items()}
    shown = ", ".join(
        f"{k.replace('_', ' ')} {v:.2f}" for k, v in list(values.items())[:2]
    )
    words = KIND_WORDS.get(moment.kind, moment.kind.replace("_", " "))
    return Overlay(
        overlay_id=f"{moment.moment_id}-card",
        match_id=context.match_id,
        kind=moment.kind,
        slot="stat_card",
        t_in=OverlayTime(match=moment.clock, wall=datetime.now(UTC)),
        duration_ms=4000,
        priority=round(moment.importance * 100),
        risk_tier="low",
        text={"en": f"{team}: {words}" + (f" ({shown})" if shown else "")},
        values=values,
        evidence_event_ids=moment.evidence_event_ids,
        status="pending",
    )
