"""Football MCP server (Phase 3a): the only way agents get numbers.

Read-only, typed tools over one match. Every number comes from core.metrics /
core.moments and carries the event ids behind it. There is no raw query tool:
an agent can ask for a registered metric, a comparison, the events around a
moment, a freeze frame, a player's context or the moments so far, nothing
else.

    uv run python -m agents.mcp_server --match-file demo/match.jsonl   # stdio
    uv run python -m agents.mcp_server --database                      # interpreter's Postgres
"""

from typing import Annotated

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from agents.mcp_server.data import MatchData
from core.contracts import Moment
from core.metrics import METRICS, play, positional
from core.metrics.events import PASSES, SHOTS, TOUCHES
from core.moments import at_window

READ_ONLY = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
)
TOOLS = (
    "get_metric",
    "compare_windows",
    "get_sequence",
    "get_freeze_frame",
    "get_player_context",
    "list_moments",
)
MAX_AROUND = 20
Minute = Annotated[int, Field(ge=0, le=130)]


class MetricResult(BaseModel):
    name: str
    team: str | None
    window: str
    value: float | None  # None: undefined here (e.g. PPDA with no defensive actions)
    numerator: float | None = None
    denominator: float | None = None
    unit: str
    display_name: dict[str, str]
    evidence_event_ids: list[str]


class Comparison(BaseModel):
    metric: str
    team: str | None
    a: tuple[int, int]
    b: tuple[int, int]
    value_a: float | None
    value_b: float | None
    change: float | None
    unit: str
    evidence_event_ids_a: list[str]
    evidence_event_ids_b: list[str]


class EventSummary(BaseModel):
    event_id: str
    period: int
    minute: int
    second: int
    team_id: str
    player_id: str
    type: str
    outcome: str
    start: tuple[float, float]
    end: tuple[float, float]
    under_pressure: bool
    xg: float | None = None


class Sequence(BaseModel):
    centre_event_id: str
    events: list[EventSummary]
    evidence_event_ids: list[str]


class Player(BaseModel):
    player_id: str
    team_id: str
    x: float
    y: float
    facing_deg: float


class FreezeFrame(BaseModel):
    event_id: str
    frame: str = "SPADL: the acting team attacks towards x = 105"
    acting_team: str
    players: list[Player]
    pressure: float
    risk: float
    options: float
    evidence_event_ids: list[str]


class PlayerContext(BaseModel):
    player_id: str
    team_id: str
    touches: int
    passes: int
    passes_completed: int
    shots: int
    xg: float
    xt_added: float
    bad_situations: int
    evidence_event_ids: list[str]


class Moments(BaseModel):
    since_minute: int
    moments: list[Moment]


def summary(e) -> EventSummary:
    xg = e.qualifiers.get("xg")
    return EventSummary(
        event_id=e.event_id,
        period=e.period,
        minute=e.minute,
        second=e.second,
        team_id=e.team_id,
        player_id=e.player_id,
        type=e.type,
        outcome=e.outcome,
        start=(e.start_x, e.start_y),
        end=(e.end_x, e.end_y),
        under_pressure=e.under_pressure,
        xg=float(xg) if xg is not None else None,
    )


def build(data: MatchData) -> MCPServer:
    """An MCP server over one match. Tools only read `data`."""
    teams = data.events.teams
    server = MCPServer(
        "second-ball-football",
        instructions=(
            "Read-only football numbers for one match. Never compute or invent a "
            "number: quote what the tools return, with its evidence_event_ids. "
            f"Teams: {teams[0]} (home), {teams[1]} (away)."
        ),
    )

    def metric(name: str):
        if name not in METRICS:
            raise ValueError(f"unknown metric {name!r}; known: {sorted(METRICS)}")
        return METRICS[name]

    def owner(m, team: str | None):
        if m.grain in ("match", "event"):
            return None
        if team not in teams:
            raise ValueError(f"{m.name} needs team = one of {list(teams)}")
        return team

    def index(event_id: str) -> int:
        if event_id not in data.by_id:
            raise ValueError(f"unknown event_id {event_id!r}")
        return data.by_id[event_id]

    @server.tool(annotations=READ_ONLY)
    def get_metric(
        name: str, team: str | None = None, window: str = "match"
    ) -> MetricResult:
        """A registered metric now. window: "match" (whole match so far) or a
        number of minutes ("5", "10", ...) the metric supports. Event metrics
        (pressure, risk, ...) give the latest event's value; use
        get_freeze_frame for a specific event."""
        m = metric(name)
        who = owner(m, team)
        minutes = None if window == "match" else int(window)
        if m.grain != "event" and minutes not in m.windows:
            raise ValueError(f"{name} supports windows {m.windows} (None = match)")
        v = m.compute(data.events, who, minutes)
        return MetricResult(
            name=name,
            team=who,
            window=window,
            value=None if v is None else v.value,
            numerator=None if v is None else v.numerator,
            denominator=None if v is None else v.denominator,
            unit=m.unit,
            display_name=m.display_name,
            evidence_event_ids=[] if v is None else v.evidence_event_ids,
        )

    @server.tool(annotations=READ_ONLY)
    def compare_windows(
        metric_name: str,
        team: str | None,
        a: tuple[Minute, Minute],
        b: tuple[Minute, Minute],
    ) -> Comparison:
        """A team or match metric over two windows of match minutes, e.g.
        a = (50, 60), b = (60, 70): value in each and the change (b - a)."""
        m = metric(metric_name)
        if m.grain == "event":
            raise ValueError("compare_windows needs a team or match metric")
        who = owner(m, team)
        values = []
        for lo, hi in (a, b):
            if hi <= lo:
                raise ValueError("a window is (from_minute, to_minute) with to > from")
            values.append(at_window(m.fn, data.events, lo * 60, hi * 60, who))
        va, vb = values
        return Comparison(
            metric=metric_name,
            team=who,
            a=a,
            b=b,
            value_a=va and va.value,
            value_b=vb and vb.value,
            change=(vb.value - va.value) if va and vb else None,
            unit=m.unit,
            evidence_event_ids_a=va.evidence_event_ids if va else [],
            evidence_event_ids_b=vb.evidence_event_ids if vb else [],
        )

    @server.tool(annotations=READ_ONLY)
    def get_sequence(
        event_id: str,
        before: Annotated[int, Field(ge=0, le=MAX_AROUND)] = 5,
        after: Annotated[int, Field(ge=0, le=MAX_AROUND)] = 5,
    ) -> Sequence:
        """The events just before and after an event (at most 20 each way)."""
        k = index(event_id)
        items = data.events.items[max(0, k - before) : k + after + 1]
        return Sequence(
            centre_event_id=event_id,
            events=[summary(e) for e in items],
            evidence_event_ids=[e.event_id for e in items],
        )

    @server.tool(annotations=READ_ONLY)
    def get_freeze_frame(event_id: str) -> FreezeFrame:
        """Every player's position and facing at an event, with the pressure,
        risk and safe options of the player on the ball."""
        k = index(event_id)
        e = data.events.items[k]
        return FreezeFrame(
            event_id=event_id,
            acting_team=e.team_id,
            players=[Player(**p.model_dump()) for p in e.freeze_frame],
            pressure=positional.pressure(data.events, k).value,
            risk=positional.risk(data.events, k).value,
            options=positional.options(data.events, k).value,
            evidence_event_ids=[event_id],
        )

    @server.tool(annotations=READ_ONLY)
    def get_player_context(player_id: str) -> PlayerContext:
        """A player's match so far: touches, passes, shots, xG, xT added and
        bad situations, with every event behind them."""
        ks = [k for k, e in enumerate(data.events.items) if e.player_id == player_id]
        if not ks:
            raise ValueError(f"unknown player_id {player_id!r}")
        es = [data.events.items[k] for k in ks]
        added = [play.xt_added(data.events, k) for k in ks]
        return PlayerContext(
            player_id=player_id,
            team_id=es[0].team_id,
            touches=sum(e.type in TOUCHES for e in es),
            passes=sum(e.type in PASSES for e in es),
            passes_completed=sum(
                e.type in PASSES and e.outcome == "success" for e in es
            ),
            shots=sum(e.type in SHOTS for e in es),
            xg=sum(float(e.qualifiers.get("xg", 0.0)) for e in es if e.type in SHOTS),
            xt_added=sum(v.value for v in added if v is not None),
            bad_situations=sum(
                int(positional.bad_situation(data.events, k).value)
                for k in ks
                if data.events.items[k].type in TOUCHES
            ),
            evidence_event_ids=[e.event_id for e in es],
        )

    @server.tool(annotations=READ_ONLY)
    def list_moments(since_minute: Minute = 0) -> Moments:
        """Moments the detector found from a match minute on, in order."""
        return Moments(
            since_minute=since_minute,
            moments=[m for m in data.moments if m.clock.minute >= since_minute],
        )

    return server


__all__ = ["TOOLS", "MatchData", "build"]
