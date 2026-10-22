"""Interpreter: consumes match-events and keeps a live MatchState per match.

    uv run python -m stream.interpreter [--timeline docs/timelines/demo.csv --exit-on-end]

Reads EVENTS ONLY (the contracts on the topic), never engine internals. Plain
code, no model: every number comes from core.metrics and carries the event ids
that produced it. Each event is stored (deduped on event_id) before it is
counted; the Kafka offset is committed after, so a crash replays at most a few
events, which the store then skips.
"""

import argparse
import time
from pathlib import Path

from core.contracts import Match, MatchEvent, MatchState
from core.metrics import Events, match_state
from stream import kafka
from stream.interpreter.store import Store
from stream.interpreter.timeline import write_timeline

# The live MatchState updates on every event; the copy in Postgres (for
# readers, not for correctness: a restart rebuilds from the stored events) is
# written at most this often, and always at MatchEnd. A full-time state is
# ~1 MB, too much to write 16 times a second at 60x.
SAVE_EVERY_S = 1.0


class Interpreter:
    def __init__(self, store: Store):
        self.store = store
        self.matches: dict[str, Events] = {}
        self.latencies_s: list[float] = []
        self.latest: dict[str, MatchState] = {}  # live state, per match
        self.saved_at: dict[str, float] = {}  # monotonic time of the last save
        self.saves = 0
        for match, events in store.load():
            self.matches[match.match_id] = Events.for_match(match, events)

    def on_match(self, match: Match) -> None:
        self.store.record_match(match)
        self.matches.setdefault(match.match_id, Events.for_match(match))

    def on_event(self, event: MatchEvent) -> MatchState | None:
        """New event: update and return the MatchState. Duplicate: None."""
        if event.match_id not in self.matches:
            raise LookupError(f"event for unknown match {event.match_id}")
        if not self.store.record_event(event):
            return None
        events = self.matches[event.match_id]
        events.append(event)
        state = match_state(events)
        self.latest[event.match_id] = state
        if time.monotonic() - self.saved_at.get(event.match_id, -1e9) >= SAVE_EVERY_S:
            self.save(event.match_id)
        return state

    def save(self, match_id: str) -> None:
        if match_id in self.latest:
            self.store.save_state(match_id, self.latest[match_id])
            self.saved_at[match_id] = time.monotonic()
            self.saves += 1

    def handle(self, msg) -> tuple[bytes, str]:
        contract = kafka.header(msg, "contract")
        payload = msg.value()
        if contract == kafka.MATCH:
            self.on_match(Match.model_validate_json(payload))
        elif (
            contract == kafka.EVENT
            and self.on_event(MatchEvent.model_validate_json(payload)) is not None
        ):
            sent = int(kafka.header(msg, kafka.SENT_AT))
            self.latencies_s.append((time.time_ns() - sent) / 1e9)
        match_id = msg.key().decode()
        if contract == kafka.END:
            self.save(match_id)  # the final state is always in Postgres
        return contract, match_id


def consumer(group: str = "interpreter", topic: str = kafka.TOPIC):
    from confluent_kafka import Consumer

    c = Consumer(
        kafka.config(
            **{
                "group.id": group,
                "enable.auto.commit": False,
                "auto.offset.reset": "earliest",
            }
        )
    )
    c.subscribe([topic])
    return c


def run(interp: Interpreter, c, stop_after=None, until_end=None, idle_s=None):
    """Consume until `until_end` (a match_id, or "*" for any) ends, `stop_after`
    messages were handled, or nothing arrived for `idle_s` seconds.
    Returns (messages handled, match_id that ended or None)."""
    handled, idle_since = 0, time.monotonic()
    while True:
        msg = c.poll(0.2)
        if msg is None:
            if idle_s is not None and time.monotonic() - idle_since > idle_s:
                return handled, None
            continue
        if msg.error():
            raise RuntimeError(msg.error())
        idle_since = time.monotonic()
        contract, match_id = interp.handle(msg)
        c.commit(message=msg, asynchronous=False)
        handled += 1
        if contract == kafka.END and until_end in (match_id, "*"):
            return handled, match_id
        if stop_after is not None and handled >= stop_after:
            return handled, None


def main(argv=None):
    from dotenv import load_dotenv

    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--topic", default=kafka.TOPIC)
    parser.add_argument("--group", default="interpreter")
    parser.add_argument("--exit-on-end", action="store_true", help="stop at MatchEnd")
    parser.add_argument("--timeline", type=Path, help="CSV path, written at MatchEnd")
    args = parser.parse_args(argv)

    kafka.ensure_topic(args.topic)
    store = Store()
    interp = Interpreter(store)
    c = consumer(args.group, args.topic)
    try:
        while True:
            _, ended = run(interp, c, until_end="*")
            if args.timeline:
                write_timeline(interp.matches[ended], args.timeline)
                print(f"timeline -> {args.timeline}")
            if interp.latencies_s:
                lat = sorted(interp.latencies_s)
                print(
                    f"{len(lat)} events, latency p50 {lat[len(lat) // 2]:.3f}s "
                    f"max {lat[-1]:.3f}s"
                )
            if args.exit_on_end:
                return
    finally:
        c.close()
        store.close()
