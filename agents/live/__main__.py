"""Live narrator: consume match-events, publish overlays.

    uv run python -m agents.live --speed 10 [--exit-on-end] [--out overlays.jsonl]

Run it, then replay a match at the same speed (make live does both). The
model comes from .env (LLM_PROVIDER, MAX_RUN_USD); traces go where
OTEL_EXPORTER says (make jaeger, then OTEL_EXPORTER=otlp).
"""

import argparse
import asyncio
import json
import time
from pathlib import Path

from agents.live import Live
from agents.llm import from_env
from agents.telemetry import flush, setup
from core.contracts import Match, MatchEvent, Overlay
from stream import kafka

OVERLAY = b"Overlay"


def kafka_sink(topic: str):
    from confluent_kafka import Producer

    kafka.ensure_topic(topic)
    p = Producer(kafka.config())

    def publish(o: Overlay) -> None:
        p.produce(
            topic,
            key=o.match_id.encode(),
            value=o.model_dump_json().encode(),
            headers=[("contract", OVERLAY), (kafka.SENT_AT, str(time.time_ns()))],
        )
        p.poll(0)

    publish.flush = p.flush
    return publish


def file_sink(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    f = path.open("a")

    def publish(o: Overlay) -> None:
        f.write(o.model_dump_json() + "\n")
        f.flush()

    return publish


def fan_out(*sinks):
    def publish(o: Overlay) -> None:
        for s in sinks:
            s(o)

    return publish


async def serve(live: Live, consumer, exit_on_end: bool) -> None:
    worker = asyncio.create_task(live.worker())
    seen: set[str] = set()  # redelivered events are skipped
    try:
        while True:
            msg = await asyncio.to_thread(consumer.poll, 0.2)
            if msg is None:
                continue
            if msg.error():
                raise RuntimeError(msg.error())
            contract = kafka.header(msg, "contract")
            if contract == kafka.MATCH:
                live.on_match(Match.model_validate_json(msg.value()))
            elif contract == kafka.EVENT:
                event = MatchEvent.model_validate_json(msg.value())
                if event.event_id not in seen and event.match_id in live.games:
                    seen.add(event.event_id)
                    if sent := kafka.header(msg, kafka.SENT_AT):
                        live.stats.transport_s.append(
                            (time.time_ns() - int(sent)) / 1e9
                        )
                    live.on_event(event)
            elif contract == kafka.END:
                match_id = msg.key().decode()
                if match_id in live.games:
                    live.on_end(match_id)
                    if exit_on_end:
                        await live.drain()
                        return
            consumer.commit(message=msg, asynchronous=True)
            await asyncio.sleep(0)  # let the worker run between events
    finally:
        worker.cancel()


def main(argv=None):
    from dotenv import load_dotenv

    load_dotenv()
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--topic", default=kafka.TOPIC)
    p.add_argument("--group", default="narrator")
    p.add_argument("--overlay-topic", default="overlays")
    p.add_argument("--out", type=Path, help="also append overlays to this JSONL")
    p.add_argument("--speed", type=float, default=10, help="the replay speed")
    p.add_argument("--personas", default="casual,analyst")
    p.add_argument("--languages", default="fr,es,sw,ar", help="'' for English only")
    p.add_argument("--min-importance", type=float, default=0.7)
    p.add_argument("--exit-on-end", action="store_true")
    p.add_argument(
        "--from-start", action="store_true", help="read the topic from the start"
    )
    args = p.parse_args(argv)

    setup()
    from confluent_kafka import Consumer

    kafka.ensure_topic(args.topic)
    consumer = Consumer(
        kafka.config(
            **{
                "group.id": args.group,
                "enable.auto.commit": False,
                # A live broadcast starts now, not from old replays.
                "auto.offset.reset": "earliest" if args.from_start else "latest",
            }
        )
    )
    consumer.subscribe([args.topic])
    sinks = [kafka_sink(args.overlay_topic)]
    if args.out:
        sinks.append(file_sink(args.out))
    llm = from_env()
    live = Live(
        llm,
        fan_out(*sinks),
        personas=[x for x in args.personas.split(",") if x],
        languages=[x for x in args.languages.split(",") if x],
        speed=args.speed,
        min_importance=args.min_importance,
    )
    try:
        asyncio.run(serve(live, consumer, args.exit_on_end))
    except KeyboardInterrupt:
        pass
    finally:
        consumer.close()
        sinks[0].flush(10)
        flush()
        s = live.stats
        print(
            json.dumps(
                {
                    "outcomes": dict(s.outcomes),
                    "narrated": len(s.narrate_s),
                    "llm_usd": round(llm.budget.usd_spent, 4),
                }
            )
        )


if __name__ == "__main__":
    main()
