"""The metric registry (semantic layer): every metric declared once.

Agents get numbers only through here. They read names, definitions and
display names; they never compute.
"""

from bisect import bisect_right
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from core.contracts import MetricValue
from core.metrics import basic, chaos, play, positional
from core.metrics.events import Events

Grain = Literal["match", "team", "player", "window", "event"]
Frame = Literal["SPADL", "broadcast"]
Persona = Literal["analyst", "casual"]

# Rolling windows in minutes; None = the whole match so far.
WINDOWS: tuple[int | None, ...] = (None, 5, 10, 15)
MATCH_KEY = "match"  # MatchState.metrics key for match-grain metrics
EVENT_KEY = (
    "last_event"  # MatchState.metrics key: event-grain values of the latest event
)


@dataclass(frozen=True)
class Metric:
    name: str
    definition: str
    grain: Grain
    unit: str
    frame: Frame
    # Personas it is shown to; analyst-only metrics have no casual name.
    display_name: dict[Persona, str]
    fn: Callable[..., MetricValue | None]
    windows: tuple[int | None, ...] = WINDOWS

    @property
    def formula(self) -> str:
        """Reference to the one function that computes it."""
        return f"{self.fn.__module__}.{self.fn.__name__}"

    def compute_event(self, events: Events, i: int):
        """Event-grain metrics: the value for event i."""
        return self.fn(events, i)

    def compute(self, events: Events, team: str | None = None, minutes=None):
        if self.grain == "event":  # its value for the latest event
            return (
                self.compute_event(events, len(events.items) - 1)
                if events.items
                else None
            )
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
            display_name={"analyst": "Possession changes / min"},
            fn=basic.possession_changes_per_min,
        ),
        Metric(
            name="field_tilt",
            definition=(
                "Share of all final-third touches (each team in its own attacking "
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
        Metric(
            name="xt_share",
            definition=(
                "Share of all expected threat (xT) added by successful passes and "
                "carries that the team added."
            ),
            grain="team",
            unit="share 0-1",
            frame="SPADL",
            display_name={"analyst": "xT share", "casual": "Who is creating danger"},
            fn=chaos.xt_share,
            windows=(None, 10),
        ),
        Metric(
            name="control_index",
            definition=(
                "Mean of possession (time), field tilt and xT share over the last "
                "10 minutes: how much the team is running the match."
            ),
            grain="team",
            unit="index 0-1",
            frame="SPADL",
            display_name={"analyst": "Control index", "casual": "Who is in control"},
            fn=chaos.control_index,
            windows=(10,),
        ),
        Metric(
            name="two_way_threat",
            definition="The smaller of the two teams' xG in the window.",
            grain="match",
            unit="goals",
            frame="SPADL",
            display_name={
                "analyst": "Two-way threat (min xG)",
                "casual": "Both teams creating chances",
            },
            fn=chaos.two_way_threat,
            windows=(10,),
        ),
        Metric(
            name="threat_switches",
            definition=(
                "Times the team creating threat (a shot, or the ball reaching high "
                "xT) changes sides."
            ),
            grain="match",
            unit="count",
            frame="SPADL",
            display_name={
                "analyst": "Threat switches",
                "casual": "How often the danger switches ends",
            },
            fn=chaos.threat_switches,
            windows=(10,),
        ),
        Metric(
            name="transition_speed",
            definition=(
                "Median seconds from winning the ball in open play to a shot or "
                "getting it into the box."
            ),
            grain="match",
            unit="seconds",
            frame="SPADL",
            display_name={
                "analyst": "Transition speed (regain to shot/box)",
                "casual": "How fast they attack after winning it",
            },
            fn=chaos.transition_speed,
            windows=(10,),
        ),
        Metric(
            name="openness_index",
            definition=(
                "Mean of two-way threat, threat switches and transition speed, each "
                "scaled 0-1: how end-to-end the match is."
            ),
            grain="match",
            unit="index 0-1",
            frame="SPADL",
            display_name={
                "analyst": "Openness index",
                "casual": "How end-to-end it is",
            },
            fn=chaos.openness_index,
            windows=(10,),
        ),
        Metric(
            name="openness_vs_expected",
            definition=(
                "Openness minus the usual openness of fixtures with the same "
                "pre-match strength gap (0 = as usual)."
            ),
            grain="match",
            unit="index difference",
            frame="SPADL",
            display_name={
                "analyst": "Openness vs expected",
                "casual": "More or less open than usual for this fixture",
            },
            fn=chaos.openness_vs_expected,
            windows=(10,),
        ),
        Metric(
            name="short_possessions",
            definition="Share of possessions with fewer than 3 passes.",
            grain="match",
            unit="share 0-1",
            frame="SPADL",
            display_name={"analyst": "Short possessions (<3 passes)"},
            fn=chaos.short_possessions,
            windows=(None, 10),
        ),
        Metric(
            name="loose_balls",
            definition="Times the ball got away from a player (bad touches), per minute.",
            grain="match",
            unit="per minute",
            frame="SPADL",
            display_name={"analyst": "Loose balls / min"},
            fn=chaos.loose_balls,
            windows=(None, 10),
        ),
        Metric(
            name="pressure",
            definition="Pressure on the player on the ball (0-1): nearby opponents, doubled in front or goal-side.",
            grain="event",
            unit="index 0-1",
            frame="SPADL",
            display_name={
                "analyst": "Pressure on the ball",
                "casual": "How hard he is pressed",
            },
            fn=positional.pressure,
            windows=(None,),
        ),
        Metric(
            name="risk",
            definition="How costly losing the ball here would be (0-1): high near his own goal, about 0 when his team has the upper hand in the final third.",
            grain="event",
            unit="index 0-1",
            frame="SPADL",
            display_name={
                "analyst": "Risk of losing it here",
                "casual": "How dangerous a mistake here would be",
            },
            fn=positional.risk,
            windows=(None,),
        ),
        Metric(
            name="options",
            definition="Teammates with a clear passing lane (no opponent within 2 m), not clearly offside.",
            grain="event",
            unit="count",
            frame="SPADL",
            display_name={
                "analyst": "Safe passing options",
                "casual": "Free teammates to pass to",
            },
            fn=positional.options,
            windows=(None,),
        ),
        Metric(
            name="facing_own_goal",
            definition="1 if the player on the ball faces his own goal (120-240 degrees).",
            grain="event",
            unit="flag",
            frame="SPADL",
            display_name={
                "analyst": "Facing own goal",
                "casual": "Facing his own goal",
            },
            fn=positional.facing_own_goal,
            windows=(None,),
        ),
        Metric(
            name="bad_situation",
            definition="1 if risk >= 0.6, facing own goal, and pressure >= 0.5 or no safe option.",
            grain="event",
            unit="flag",
            frame="SPADL",
            display_name={
                "analyst": "Danger on the ball",
                "casual": "In trouble on the ball",
            },
            fn=positional.bad_situation,
            windows=(None,),
        ),
        Metric(
            name="lines_broken",
            definition="Defending lines a pass crosses going forward (up to 3 lines from the freeze frame).",
            grain="event",
            unit="count",
            frame="SPADL",
            display_name={
                "analyst": "Lines broken",
                "casual": "Lines the pass cut through",
            },
            fn=positional.lines_broken,
            windows=(None,),
        ),
        Metric(
            name="line_gap",
            definition="Metres between the defending team's back line and midfield line.",
            grain="event",
            unit="metres",
            frame="SPADL",
            display_name={
                "analyst": "Back-midfield line gap",
                "casual": "Space between their defence and midfield",
            },
            fn=positional.line_gap,
            windows=(None,),
        ),
        Metric(
            name="overload",
            definition="Danger-weighted overload around the ball: attackers minus defenders >= 1 in a box 20 m ahead and 10 m behind in the ball's lane (numerator attackers, denominator defenders).",
            grain="event",
            unit="danger 0-1",
            frame="SPADL",
            display_name={
                "analyst": "Overload",
                "casual": "Outnumbering them near the ball",
            },
            fn=positional.overload,
            windows=(None,),
        ),
        Metric(
            name="xt_added",
            definition="Expected threat added by this pass or carry.",
            grain="event",
            unit="xT",
            frame="SPADL",
            display_name={"analyst": "xT added", "casual": "Danger added by this move"},
            fn=play.xt_added,
            windows=(None,),
        ),
        Metric(
            name="pass_difficulty",
            definition="Pass difficulty 0-100 (docs/metrics/pass_difficulty.md).",
            grain="event",
            unit="score 0-100",
            frame="SPADL",
            display_name={
                "analyst": "Pass difficulty",
                "casual": "How hard that pass was",
            },
            fn=play.pass_difficulty,
            windows=(None,),
        ),
        Metric(
            name="ball_speed",
            definition="Ball speed of a pass or shot.",
            grain="event",
            unit="km/h",
            frame="SPADL",
            display_name={"analyst": "Ball speed", "casual": "Ball speed"},
            fn=play.ball_speed,
            windows=(None,),
        ),
        Metric(
            name="name_tag",
            definition="1 when a shot is at least 100 km/h or a pass at least 45 m (not a goal kick): show the player's name, at most once per player per 5 minutes.",
            grain="event",
            unit="flag",
            frame="SPADL",
            display_name={"analyst": "Name-tag trigger", "casual": "Show who it was"},
            fn=play.name_tag,
            windows=(None,),
        ),
        Metric(
            name="final_third_pressures",
            definition="Opponent touches in their own third made under pressure, per minute.",
            grain="team",
            unit="per minute",
            frame="SPADL",
            display_name={
                "analyst": "Final-third pressures / min",
                "casual": "Pressing high up the pitch",
            },
            fn=play.final_third_pressures,
        ),
        Metric(
            name="high_turnovers",
            definition="Balls won in open play within 40 m of the opponent's goal.",
            grain="team",
            unit="count",
            frame="SPADL",
            display_name={"analyst": "High turnovers", "casual": "Balls won high up"},
            fn=play.high_turnovers,
        ),
        Metric(
            name="counterpress_regains",
            definition="Share of balls lost in open play won back within 5 seconds.",
            grain="team",
            unit="share 0-1",
            frame="SPADL",
            display_name={
                "analyst": "Counter-press regains (5 s)",
                "casual": "Winning it straight back",
            },
            fn=play.counterpress_regains,
        ),
        Metric(
            name="actions_per_minute",
            definition="On-ball actions per minute of the team's own possession.",
            grain="team",
            unit="per minute",
            frame="SPADL",
            display_name={
                "analyst": "Actions / min in possession",
                "casual": "Tempo on the ball",
            },
            fn=play.actions_per_minute,
        ),
        Metric(
            name="seconds_between_actions",
            definition="Median in-play seconds between consecutive events.",
            grain="match",
            unit="seconds",
            frame="SPADL",
            display_name={
                "analyst": "Seconds between actions",
                "casual": "Pace of the game",
            },
            fn=play.seconds_between_actions,
        ),
        Metric(
            name="momentum",
            definition="Exponentially weighted xT added, home minus away (half-life 3 minutes); above 0 the home team is on top.",
            grain="match",
            unit="xT",
            frame="SPADL",
            display_name={
                "analyst": "Momentum (xT, home - away)",
                "casual": "Who is on top right now",
            },
            fn=play.momentum,
            windows=(None,),
        ),
        Metric(
            name="xt_added_total",
            definition="Net expected threat added by the team's successful passes and carries (numerator xT, denominator moves).",
            grain="team",
            unit="xT",
            frame="SPADL",
            display_name={
                "analyst": "xT added",
                "casual": "Danger created by passing and carrying",
            },
            fn=play.team_xt_added,
        ),
        Metric(
            name="big_chances",
            definition="Shots with xG of at least 0.3.",
            grain="team",
            unit="count",
            frame="SPADL",
            display_name={"analyst": "Big chances", "casual": "Big chances"},
            fn=play.big_chances,
        ),
        Metric(
            name="pass_distance",
            definition="Average pass length.",
            grain="team",
            unit="metres",
            frame="SPADL",
            display_name={
                "analyst": "Average pass length",
                "casual": "How far they pass",
            },
            fn=play.pass_distance,
        ),
        Metric(
            name="pass_accuracy",
            definition="Completed passes divided by passes.",
            grain="team",
            unit="share 0-1",
            frame="SPADL",
            display_name={
                "analyst": "Pass accuracy",
                "casual": "Passes that found a teammate",
            },
            fn=play.pass_accuracy,
        ),
        Metric(
            name="lines_broken_per_pass",
            definition="Defending lines crossed per completed pass.",
            grain="team",
            unit="lines per pass",
            frame="SPADL",
            display_name={
                "analyst": "Lines broken per pass",
                "casual": "Passing through the lines",
            },
            fn=play.lines_broken_per_pass,
        ),
        Metric(
            name="pass_difficulty_mean",
            definition="Average difficulty (0-100) of the team's passes.",
            grain="team",
            unit="score 0-100",
            frame="SPADL",
            display_name={
                "analyst": "Average pass difficulty",
                "casual": "How hard their passes are",
            },
            fn=play.mean_pass_difficulty,
        ),
        Metric(
            name="fastest_shot",
            definition="Fastest shot.",
            grain="team",
            unit="km/h",
            frame="SPADL",
            display_name={"analyst": "Fastest shot", "casual": "Hardest shot"},
            fn=play.fastest_shot,
        ),
        Metric(
            name="name_tags",
            definition="Fast shots (100+ km/h) and long passes (45+ m, not goal kicks or the keeper's), at most one per player per 5 minutes.",
            grain="team",
            unit="count",
            frame="SPADL",
            display_name={
                "analyst": "Name-tag moments",
                "casual": "Standout strikes and passes",
            },
            fn=play.name_tags,
        ),
        Metric(
            name="bad_situations",
            definition="Times the team's player on the ball met the bad_situation rule (Ian's spec).",
            grain="team",
            unit="count",
            frame="SPADL",
            display_name={
                "analyst": "Dangerous moments on the ball",
                "casual": "Times caught in trouble",
            },
            fn=positional.bad_situations,
        ),
        Metric(
            name="pressure_on_ball",
            definition="Average pressure on the team's player on the ball (0-1).",
            grain="team",
            unit="index 0-1",
            frame="SPADL",
            display_name={
                "analyst": "Average pressure on the ball",
                "casual": "How much they are being pressed",
            },
            fn=positional.mean_pressure_on_ball,
        ),
        Metric(
            name="defensive_line_gap",
            definition="Average metres between the team's back line and midfield line while defending.",
            grain="team",
            unit="metres",
            frame="SPADL",
            display_name={
                "analyst": "Back-midfield gap (defending)",
                "casual": "Space between their defence and midfield",
            },
            fn=positional.team_line_gap,
        ),
        Metric(
            name="overloads",
            definition="Danger-weighted overloads the team created on the ball.",
            grain="team",
            unit="danger",
            frame="SPADL",
            display_name={"analyst": "Overloads", "casual": "Outnumbering them"},
            fn=positional.overloads,
        ),
        Metric(
            name="upper_hand",
            definition="0 none, 1 upper hand (10+ final-third touches, 2+ shots, constant pressure), 2 strong (also xG 0.5+).",
            grain="team",
            unit="level 0-2",
            frame="SPADL",
            display_name={"analyst": "Upper hand", "casual": "Who is on top"},
            fn=positional.upper_hand,
            windows=(5, 10, 15, 20, 30),
        ),
        Metric(
            name="upper_hand_checkpoint",
            definition="Upper hand in the last completed fixed 10-minute block (0-10, 10-20, ...).",
            grain="team",
            unit="level 0-2",
            frame="SPADL",
            display_name={
                "analyst": "Upper hand (10-min checkpoint)",
                "casual": "Who was on top in that spell",
            },
            fn=positional.upper_hand_checkpoint,
            windows=(None,),
        ),
    ]
}


def get(name: str) -> Metric:
    return METRICS[name]


def compute_all(events: Events) -> dict[str, dict[str, MetricValue]]:
    """Every metric, every window: metrics[team_id or "match"][key]."""
    out: dict[str, dict[str, MetricValue]] = {t: {} for t in events.teams}
    out[MATCH_KEY] = {}
    starts = {}
    for m in METRICS.values():
        if m.grain == "event":
            continue
        for minutes in m.windows:
            if minutes not in starts:
                starts[minutes] = start_index(events, minutes)
            lo = starts[minutes]
            if lo is None:
                continue
            owners = [MATCH_KEY] if m.grain == "match" else list(events.teams)
            for owner in owners:
                v = m.fn(events, lo, None if owner == MATCH_KEY else owner)
                if v is not None:
                    out[owner][key(m.name, minutes)] = v
    if events.items:
        last = len(events.items) - 1
        out[EVENT_KEY] = {
            m.name: v
            for m in METRICS.values()
            if m.grain == "event" and (v := m.fn(events, last)) is not None
        }
    return out
