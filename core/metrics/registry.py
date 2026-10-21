"""The metric registry (semantic layer): every metric declared once.

Agents get numbers only through here. They read names, definitions and
display names; they never compute.
"""

from bisect import bisect_right
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from core.contracts import MetricValue
from core.metrics import basic
from core.metrics.events import Events

Grain = Literal["match", "team", "player", "window"]
Frame = Literal["SPADL", "broadcast"]
Persona = Literal["analyst", "casual"]

# Rolling windows in minutes; None = the whole match so far.
WINDOWS: tuple[int | None, ...] = (None, 5, 10, 15)
MATCH_KEY = "match"  # MatchState.metrics key for match-grain metrics


@dataclass(frozen=True)
class Metric:
    name: str
    definition: str
    grain: Grain
    unit: str
    frame: Frame
    display_name: dict[Persona, str]
    fn: Callable[..., MetricValue | None]

    @property
    def formula(self) -> str:
        """Reference to the one function that computes it."""
        return f"{self.fn.__module__}.{self.fn.__name__}"

    def compute(self, events: Events, team: str | None = None, minutes=None):
        lo = start_index(events, minutes)
        if lo is None:
            return None
        return self.fn(events, lo, team)


def start_index(events: Events, minutes: int | None) -> int | None:
    if not events.items:
        return None
    if minutes is None:
        return 0
    # Events strictly after now - w: the window is (now - w, now].
    return bisect_right(events.elapsed, events.now() - minutes * 60)


def key(name: str, minutes: int | None) -> str:
    return name if minutes is None else f"{name}_last_{minutes}m"


METRICS: dict[str, Metric] = {
    m.name: m
    for m in [
        Metric(
            name="possession_time",
            definition="Share of in-play time the team had the ball.",
            grain="team",
            unit="share 0-1",
            frame="SPADL",
            display_name={"analyst": "Possession (time)", "casual": "Time on the ball"},
            fn=basic.possession_time,
        ),
        Metric(
            name="possession_passes",
            definition="Share of all passes (throw-ins excluded) made by the team.",
            grain="team",
            unit="share 0-1",
            frame="SPADL",
            display_name={
                "analyst": "Possession (passes)",
                "casual": "Share of the passing",
            },
            fn=basic.possession_passes,
        ),
        Metric(
            name="passes_per_possession",
            definition="Team passes divided by the possessions the team owned.",
            grain="team",
            unit="passes",
            frame="SPADL",
            display_name={
                "analyst": "Passes per possession",
                "casual": "How long they keep it",
            },
            fn=basic.passes_per_possession,
        ),
        Metric(
            name="shots",
            definition="Shots taken, including free kicks and penalties.",
            grain="team",
            unit="count",
            frame="SPADL",
            display_name={"analyst": "Shots", "casual": "Shots"},
            fn=basic.shots,
        ),
        Metric(
            name="xg",
            definition="Sum of the feed's xG over the team's shots.",
            grain="team",
            unit="goals",
            frame="SPADL",
            display_name={"analyst": "xG", "casual": "Quality of chances"},
            fn=basic.xg,
        ),
        Metric(
            name="ppda",
            definition=(
                "Opponent open-play passes in its own 60% of the pitch divided by "
                "the team's tackles, interceptions and fouls there. Lower = more "
                "pressing."
            ),
            grain="team",
            unit="passes per action",
            frame="SPADL",
            display_name={"analyst": "PPDA", "casual": "How hard they're pressing"},
            fn=basic.ppda,
        ),
        Metric(
            name="possession_changes_per_min",
            definition="Times the ball changes team, per minute.",
            grain="match",
            unit="per minute",
            frame="SPADL",
            display_name={
                "analyst": "Possession changes / min",
                "casual": "How often the ball swaps sides",
            },
            fn=basic.possession_changes_per_min,
        ),
        Metric(
            name="field_tilt",
            definition=(
                "Share of all final-third passes (each team in its own attacking "
                "third) made by the team."
            ),
            grain="team",
            unit="share 0-1",
            frame="SPADL",
            display_name={
                "analyst": "Field tilt",
                "casual": "Who is camped in whose half",
            },
            fn=basic.field_tilt,
        ),
    ]
}


def get(name: str) -> Metric:
    return METRICS[name]


def compute_all(events: Events) -> dict[str, dict[str, MetricValue]]:
    """Every metric, every window: metrics[team_id or "match"][key]."""
    out: dict[str, dict[str, MetricValue]] = {t: {} for t in events.teams}
    out[MATCH_KEY] = {}
    for minutes in WINDOWS:
        lo = start_index(events, minutes)
        if lo is None:
            continue
        for m in METRICS.values():
            owners = [MATCH_KEY] if m.grain == "match" else list(events.teams)
            for owner in owners:
                v = m.fn(events, lo, None if owner == MATCH_KEY else owner)
                if v is not None:
                    out[owner][key(m.name, minutes)] = v
    return out
