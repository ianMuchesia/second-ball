"""Shared event vocabulary for metric functions. Events only: no engine imports."""

from dataclasses import dataclass, field

from core.contracts import MatchEvent

LENGTH = 105.0

SHOTS = {"shot", "shot_freekick", "shot_penalty"}
# Throw-ins are not counted as passes (standard event-data practice; the
# realism report uses the same set).
PASSES = {
    "pass",
    "cross",
    "goalkick",
    "freekick_short",
    "freekick_crossed",
    "corner_crossed",
    "corner_short",
}
OPEN_PLAY_PASSES = {"pass", "cross"}
DEFENSIVE_ACTIONS = {"tackle", "interception", "foul"}
# The ball was dead before these: the gap leading up to one is not playing time.
RESTARTS = {
    "throw_in",
    "goalkick",
    "freekick_short",
    "freekick_crossed",
    "corner_crossed",
    "corner_short",
    "shot_freekick",
    "shot_penalty",
}

# On-ball actions ("touches"): everything a team does with the ball.
TOUCHES = PASSES | SHOTS | {"throw_in", "dribble", "take_on", "bad_touch", "clearance"}
LOOSE_BALLS = {"bad_touch"}  # the ball got away from the player

# The opponent's penalty area, in the acting team's frame.
BOX_X = 105.0 - 16.5
BOX_Y = (34.0 - 20.16, 34.0 + 20.16)

PPDA_ZONE_X = 63.0  # the passing team's own 60% (its frame)
FINAL_THIRD_X = 70.0  # the acting team's final third (its frame)


def in_box(x: float, y: float) -> bool:
    return x >= BOX_X and BOX_Y[0] <= y <= BOX_Y[1]


def is_goal(e: MatchEvent) -> bool:
    return (e.type in SHOTS and e.outcome == "success") or e.outcome == "owngoal"


@dataclass
class Events:
    """Events in feed order, with a continuous match clock.

    `elapsed[i]` is seconds of match time at event i, counting both halves end to
    end (first-half stoppage time included), so a "last 5 minutes" window early in
    the second half reaches back into first-half stoppage time.
    """

    teams: tuple[str, str]  # (home, away)
    # Public pre-match ratings from the Match contract (home, away), if known.
    strengths: tuple[float, float] | None = None
    items: list[MatchEvent] = field(default_factory=list)
    elapsed: list[float] = field(default_factory=list)
    owner: dict[str, str] = field(default_factory=dict)  # possession_id -> team
    _defensive_only: set[str] = field(default_factory=set)
    _period: int = 1
    _offset: float = 0.0
    _last: float = 0.0

    def append(self, e: MatchEvent) -> None:
        t = e.minute * 60 + e.second
        if e.period != self._period:
            # A new period starts where the previous one ended.
            self._offset = self._last - t
            self._period = e.period
        self._last = max(self._last, t + self._offset)
        self.items.append(e)
        self.elapsed.append(self._last)
        # A possession belongs to the first team on the ball in it; a tackle,
        # interception or foul inside it is the other side ending it.
        pid = e.possession_id
        if pid not in self.owner or pid in self._defensive_only:
            self.owner[pid] = e.team_id
            if e.type in DEFENSIVE_ACTIONS:
                self._defensive_only.add(pid)
            else:
                self._defensive_only.discard(pid)

    @classmethod
    def of(cls, teams, events, strengths=None) -> "Events":
        out = cls(teams=tuple(teams), strengths=strengths)
        for e in events:
            out.append(e)
        return out

    def opponent(self, team: str) -> str:
        home, away = self.teams
        return away if team == home else home

    @classmethod
    def for_match(cls, match, events=()) -> "Events":
        return cls.of(
            (match.home_team, match.away_team),
            events,
            (match.home_strength, match.away_strength),
        )

    def now(self) -> float:
        return self.elapsed[-1] if self.elapsed else 0.0
