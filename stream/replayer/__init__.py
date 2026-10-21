"""Replay a match file into Kafka as if it were live.

    uv run python -m stream.replayer demo/match.jsonl --speed 10

The file is a JSONL from engine.generate: the Match, then its MatchEvents.
Messages go to topic match-events keyed by match_id: the Match first, every
event when its match time comes (1x = real time), then a MatchEnd marker.
"""

import argparse
import time
from pathlib import Path

from confluent_kafka import Producer

from core.contracts import Match, MatchEvent
from stream import kafka

SPEEDS = (1, 10, 60)


def read(path: Path) -> tuple[Match, list[MatchEvent]]:
    lines = path.read_text().splitlines()
    return Match.model_validate_json(lines[0]), [
        MatchEvent.model_validate_json(line) for line in lines[1:] if line
    ]


def delays(events: list[MatchEvent]) -> list[float]:
    """Match seconds to wait before each event; no wait across half-time."""
    out, prev = [], None
    for e in events:
        t = e.minute * 60 + e.second
        out.append(0.0 if prev is None or prev[0] != e.period else max(0, t - prev[1]))
        prev = (e.period, t)
    return out


def replay(path: Path, speed: float, topic: str = kafka.TOPIC, producer=None) -> Match:
    match, events = read(path)
    producer = producer or Producer(kafka.config(**{"enable.idempotence": True}))
    key = match.match_id.encode()

    def send(contract, payload: str):
        stamp = str(time.time_ns()).encode()
        producer.produce(
            topic,
            key=key,
            value=payload.encode(),
            headers=[("contract", contract), (kafka.SENT_AT, stamp)],
        )
        producer.poll(0)

    send(kafka.MATCH, match.model_dump_json())
    producer.flush()  # connected before the match clock starts
    start, due = time.monotonic(), 0.0
    for event, wait in zip(events, delays(events), strict=True):
        due += wait / speed
        if (sleep := start + due - time.monotonic()) > 0:
            producer.flush()  # everything already due goes out before we sleep
            time.sleep(sleep)
        send(kafka.EVENT, event.model_dump_json())
    send(kafka.END, match.model_dump_json())
    producer.flush()
    return match


def wait_for_group(group: str, timeout_s: float = 60) -> None:
    """Block until a member of consumer group `group` has been assigned a
    partition, so the first events are not timed against its start-up."""
    from confluent_kafka.admin import AdminClient

    admin = AdminClient(kafka.config())
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        found = admin.describe_consumer_groups([group])[group]
        if found.exception(timeout=10) is None and any(
            m.assignment.topic_partitions for m in found.result().members
        ):
            return
        time.sleep(0.5)
    raise TimeoutError(f"no consumer in group {group!r} after {timeout_s:.0f}s")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("match_file", type=Path)
    parser.add_argument("--speed", type=float, default=10, help="1, 10 or 60")
    parser.add_argument("--topic", default=kafka.TOPIC)
    parser.add_argument(
        "--wait-for-group", metavar="GROUP", help="start once GROUP is consuming"
    )
    args = parser.parse_args(argv)
    from dotenv import load_dotenv

    load_dotenv()
    if args.speed not in SPEEDS:
        parser.error(f"--speed must be one of {SPEEDS}")
    kafka.ensure_topic(args.topic)
    if args.wait_for_group:
        wait_for_group(args.wait_for_group)
    match = replay(args.match_file, args.speed, args.topic)
    print(f"replayed {match.match_id} at {args.speed:g}x to {args.topic}")


if __name__ == "__main__":
    main()
