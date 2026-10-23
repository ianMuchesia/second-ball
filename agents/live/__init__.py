"""Live narration: match events in, overlays out. Phase 3 end to end.

    match-events -> detector -> stat card (code, airs at once)
                             -> narrate (agents; important moments) -> Producer
    second half starts / MatchEnd -> recap (aired lines + MatchState)
    -> overlays (Kafka topic and/or JSONL), every status change

One worker narrates at a time (the model's request limit), most important
moment first; a moment already too old to air is skipped, so no model call
is wasted on it. Every narrated moment is one trace: moment -> narrate ->
analyst / narrator / verifier / localizer -> producer.offer, and
producer.air / producer.expire join the same trace later.
Reads events only (the contracts), like the interpreter; never the engine.
"""

import asyncio
import itertools
import logging
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field

from agents.llm import LLMClient
from agents.mcp_server import build as build_mcp
from agents.mcp_server.data import MatchData
from agents.pipeline.facts import context_at, task_for
from agents.pipeline.models import NarrationTask, Persona
from agents.pipeline.producer import FRESH_S, Producer, stat_card
from agents.pipeline.recap import Aired, recap
from agents.pipeline.resilience import Policy, mcp_tools
from agents.pipeline.workflow import narrate
from agents.telemetry import child_of, step, tracer
from core.contracts import Match, MatchEvent, Moment, Overlay
from core.metrics import Events
from core.moments import MomentDetector

log = logging.getLogger(__name__)

MIN_IMPORTANCE = 0.7  # narrate goals, red cards, big chances; others get a card
HALF_TIME, FULL_TIME = 0.5, 1.0  # job priorities: after any waiting moment


@dataclass
class Game:
    match: Match
    events: Events
    detector: MomentDetector = field(default_factory=MomentDetector)
    moments: list[Moment] = field(default_factory=list)
    aired: list[Aired] = field(default_factory=list)
    half_time_done: bool = False
    ended: bool = False

    @property
    def now(self) -> float:
        """Match seconds of the latest event (the Producer's clock)."""
        return self.events.elapsed[-1] if self.events.items else 0.0


@dataclass
class Stats:
    """Wall-clock latencies, for the latency report (seconds)."""

    transport_s: list[float] = field(default_factory=list)  # replayer -> here (Kafka)
    detect_s: list[float] = field(default_factory=list)
    queue_s: list[float] = field(default_factory=list)  # moment -> worker starts
    narrate_s: list[float] = field(default_factory=list)
    air_delay_s: list[float] = field(default_factory=list)  # moment -> on air, viewer s
    outcomes: dict[str, int] = field(default_factory=lambda: defaultdict(int))


class Live:
    def __init__(
        self,
        llm: LLMClient,
        publish: Callable[[Overlay], None],
        personas: list[Persona] = ("casual", "analyst"),
        languages: list[str] = ("fr", "es", "sw", "ar"),
        speed: float = 1.0,
        min_importance: float = MIN_IMPORTANCE,
        policy: Policy | None = None,
    ):
        self.llm, self.publish = llm, publish
        self.personas, self.languages = list(personas), list(languages)
        self.speed, self.min_importance = speed, min_importance
        self.policy = policy or Policy()
        self.games: dict[str, Game] = {}
        self.producers: dict[tuple[str, str], Producer] = {}
        self.tasks: dict[str, NarrationTask] = {}  # overlay_id -> its task
        self.traces: dict[str, object] = {}  # overlay_id -> moment span context
        self.moment_t: dict[str, float] = {}  # overlay_id -> moment match seconds
        self.queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self.order = itertools.count()
        self.stats = Stats()
        # One record per line made (narration or recap): verdicts with the
        # rejected drafts, the insight, and how long it took, for the run bundle.
        self.records: list[dict] = []

    # ---- input ---------------------------------------------------------------

    def on_match(self, match: Match) -> None:
        self.games.setdefault(
            match.match_id, Game(match=match, events=Events.for_match(match))
        )

    def on_event(self, event: MatchEvent) -> None:
        game = self.games[event.match_id]
        if (
            event.period == 2
            and not game.half_time_done
            and game.events.items
            and game.events.items[-1].period == 1
        ):
            game.half_time_done = True
            self.put(HALF_TIME, ("recap", event.match_id, "half_time"))
        game.events.append(event)
        t0 = time.perf_counter()
        moments = game.detector.update(game.events)
        self.stats.detect_s.append(time.perf_counter() - t0)
        for m in moments:
            game.moments.append(m)
            self.on_moment(game, m)
        self.tick(game)

    def on_end(self, match_id: str) -> None:
        game = self.games[match_id]
        game.ended = True
        self.put(FULL_TIME, ("recap", match_id, "full_time"))

    def put(self, priority: float, job) -> None:
        self.queue.put_nowait((priority, next(self.order), time.monotonic(), job))

    def on_moment(self, game: Game, m: Moment) -> None:
        ctx = context_at(self.snapshot(game), m)
        card = stat_card(m, ctx)
        with step("producer.offer", overlay_id=card.overlay_id, slot="stat_card"):
            for shown in self.producer(game, "cards").offer(
                card, game.now, 0, game.now
            ):
                self.out(shown)
        if m.importance >= self.min_importance:
            # Freshness counts from when the moment FIRED (Moment.clock): a red
            # card's impact fires minutes after the card, by design.
            fired = game.now
            for persona in self.personas:
                self.put(
                    -m.importance, ("moment", game.match.match_id, m, persona, fired)
                )

    # ---- work ----------------------------------------------------------------

    def snapshot(self, game: Game) -> MatchData:
        """The match so far, for facts and the MCP tools (moments preset)."""
        data = MatchData(game.match, list(game.events.items))
        data.__dict__["moments"] = list(game.moments)
        return data

    def producer(self, game: Game, persona: str) -> Producer:
        key = (game.match.match_id, persona)
        if key not in self.producers:
            self.producers[key] = Producer(speed=self.speed)
        return self.producers[key]

    async def worker(self) -> None:
        while True:
            _, _, queued_at, job = await self.queue.get()
            try:
                if job[0] == "moment":
                    await self.narrate_moment(*job[1:], queued_at)
                else:
                    await self.recap(*job[1:])
            except Exception:  # one bad job must not stop the broadcast
                log.exception("live job failed: %s", job[:2])
            finally:
                self.queue.task_done()

    async def narrate_moment(
        self, match_id, m: Moment, persona, moment_t: float, queued_at
    ) -> None:
        game = self.games[match_id]
        prod = self.producer(game, persona)
        data = self.snapshot(game)
        self.stats.queue_s.append(time.monotonic() - queued_at)
        with step(
            "moment",
            moment_id=m.moment_id,
            kind=m.kind,
            minute=m.clock.minute,
            persona=persona,
            importance=m.importance,
        ) as span:
            if game.now - moment_t > prod.fresh_s:
                span.set_attribute("decision", "skipped_stale")
                self.stats.outcomes["skipped_stale"] += 1
                return
            task = task_for(data, m, persona, self.languages)
            t0 = time.monotonic()
            out = await narrate(self.llm, task, self.policy, mcp_tools(build_mcp(data)))
            self.stats.narrate_s.append(time.monotonic() - t0)
            oid = out.overlay.overlay_id
            self.tasks[oid], self.moment_t[oid] = task, moment_t
            self.traces[oid] = span.get_span_context()
            self.record(out, task, queued_at, span)
            with step("producer.offer", overlay_id=oid, risk=out.overlay.risk_tier):
                shown = prod.offer(out.overlay, moment_t, m.importance, game.now)
                if out.overlay.risk_tier == "high":
                    self.out(prod.queue[-1].overlay)  # pending: waits for a human
            for o in shown:
                self.aired(game, o)
        self.tick(game)

    async def recap(self, match_id, when) -> None:
        game = self.games[match_id]
        data = self.snapshot(game)
        last = data.events.items[-1]
        upto = [e for e in data.events.items if when == "full_time" or e.period == 1]
        events = Events.for_match(game.match, upto)
        ctx = context_at(
            MatchData(game.match, upto),
            Moment(
                moment_id=f"{match_id}-{when}",
                kind=when,
                team=None,
                clock=last.model_dump(include={"period", "minute", "second"}),
                importance=1.0,
                metrics_before={},
                metrics_after={},
                evidence_event_ids=[upto[-1].event_id],
            ),
        )
        for persona in self.personas:
            aired = [a for a in game.aired if a.task.persona == persona]
            queued_at = time.monotonic()
            with step("moment", kind=f"recap_{when}", persona=persona) as span:
                out = await recap(
                    self.llm,
                    when,
                    events,
                    ctx,
                    aired,
                    persona,
                    self.languages,
                    self.policy,
                )
                self.record(out, None, queued_at, span)
                for o in self.producer(game, persona).offer(
                    out.overlay, game.now, 1.0, game.now
                ):
                    self.out(o)
        if when == "full_time":
            self.flush(game)

    # ---- output --------------------------------------------------------------

    def record(self, out, task: NarrationTask | None, queued_at: float, span) -> None:
        """Wall-clock latency = the moment's event available (queued) -> line
        ready (verified, translated), and whether it met the 8 s target."""
        latency = time.monotonic() - queued_at
        self.records.append(
            {
                "overlay_id": out.overlay.overlay_id,
                "kind": out.overlay.kind,
                "persona": task.persona
                if task
                else out.overlay.overlay_id.rsplit("-", 1)[-1],
                "fallback": out.fallback,
                "attempts": out.attempts,
                "verdicts": [v.model_dump(mode="json") for v in out.verdicts],
                "insight": out.insight.model_dump(mode="json") if out.insight else None,
                "latency_s": round(latency, 3),
                "met_target": latency <= FRESH_S,
                "trace_id": f"{span.get_span_context().trace_id:032x}",
                "task": task.model_dump(mode="json") if task else None,
            }
        )

    def aired(self, game: Game, o: Overlay) -> None:
        oid = o.overlay_id
        with (
            tracer.start_as_current_span(
                "producer.air", context=child_of(self.traces[oid])
            )
            if oid in self.traces
            else step("producer.air") as span
        ):
            delay = (game.now - self.moment_t.get(oid, game.now)) / self.speed
            span.set_attributes({"overlay_id": oid, "viewer_delay_s": delay})
        self.stats.air_delay_s.append(delay)
        self.stats.outcomes["aired"] += 1
        game.aired.append(Aired(o, self.tasks[oid]))
        self.out(o)

    def tick(self, game: Game) -> None:
        for persona in self.personas:
            prod = self.producer(game, persona)
            before = len(prod.expired)
            for o in prod.tick(game.now):
                self.aired(game, o)
            for o in prod.expired[before:]:
                self.expired(o)

    def expired(self, o: Overlay) -> None:
        oid = o.overlay_id
        ctx = child_of(self.traces[oid]) if oid in self.traces else None
        with tracer.start_as_current_span("producer.expire", context=ctx) as span:
            span.set_attribute("overlay_id", oid)
        self.stats.outcomes["expired"] += 1
        self.out(o)

    def flush(self, game: Game) -> None:
        """After the final whistle nothing more airs: expire what still waits."""
        for persona in self.personas:
            prod = self.producer(game, persona)
            before = len(prod.expired)
            prod.tick(game.now + prod.fresh_s + 1)
            for o in prod.expired[before:]:
                self.expired(o)

    def out(self, o: Overlay) -> None:
        try:
            self.publish(o)
        except Exception:  # a broken sink must not stop narration
            log.exception("publish failed for %s", o.overlay_id)

    async def drain(self) -> None:
        await self.queue.join()
