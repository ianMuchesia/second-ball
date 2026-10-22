"""The live narrator end to end on the demo, fake model, no Kafka: events in,
cards, narratives and both recaps out, one trace per narrated moment."""

import asyncio

from agents.live import Live
from agents.telemetry import RECORDER
from tests.unit.test_narration_report import demo
from tests.unit.test_resilience import client, fast_policy


def play(live: Live, data, wait=True):
    """Feed the match; with wait, each moment's narration finishes before the
    next event (as if the model were instant compared with the match)."""

    async def go():
        worker = asyncio.create_task(live.worker())
        live.on_match(data.match)
        for e in data.events.items:
            live.on_event(e)
            if wait:
                await live.drain()
        live.on_end(data.match.match_id)
        await live.drain()
        worker.cancel()

    asyncio.run(go())


def test_demo_end_to_end():
    RECORDER.clear()
    data = demo()
    out = []
    # At 1x the 45 s gap between narratives is 45 match seconds (see the
    # latency report for 10x, where the gap is 7.5 match minutes).
    live = Live(client(), out.append, languages=["sw"], speed=1, policy=fast_policy())
    play(live, data)
    aired = [o for o in out if o.status == "aired"]
    slots = {o.slot for o in aired}
    assert slots == {"stat_card", "narrative", "recap"}
    goals = [o for o in aired if o.slot == "narrative" and o.kind == "goal"]
    assert {o.t_in.match.minute for o in goals} == {34, 88}
    reds = [o for o in aired if o.kind == "red_card_impact" and o.slot == "narrative"]
    assert len(reds) == 2  # fires minutes after the card, still fresh
    recaps = sorted(o.kind for o in aired if o.slot == "recap")
    assert recaps == ["recap_full_time"] * 2 + ["recap_half_time"] * 2
    assert all(o.text["en"] and o.evidence_event_ids for o in out)
    # One trace per narrated moment; airing joins the same trace.
    moments = [
        s for s in RECORDER.spans if s.name == "moment" and "moment_id" in s.attributes
    ]
    airs = RECORDER.named("producer.air")
    traces = {s.context.trace_id for s in moments}
    assert airs and all(s.context.trace_id in traces for s in airs if s.parent)


def test_half_time_recap_only_uses_first_half_lines():
    data = demo()
    out = []
    live = Live(client(), out.append, languages=[], speed=10, policy=fast_policy())
    play(live, data)
    ht = [o for o in out if o.kind == "recap_half_time"]
    assert all(o.t_in.match.period == 1 for o in ht)


def test_a_slow_model_means_stale_moments_are_skipped_not_aired_late():
    data = demo()
    out = []
    live = Live(client(), out.append, languages=[], speed=10, policy=fast_policy())
    play(live, data, wait=False)  # the whole match arrives before any narration
    assert live.stats.outcomes["skipped_stale"] > 0
    late = [o for o in out if o.slot == "narrative" and o.status == "aired"]
    assert late == []  # nothing aired long after its moment
    assert any(o.kind == "recap_full_time" for o in out)  # the recap still comes


def test_through_kafka_end_to_end(kafka_env, tmp_path):
    """Replayer -> Kafka -> live narrator -> overlays topic, at 600x."""
    import uuid

    from confluent_kafka import Consumer

    from agents.live.__main__ import kafka_sink, serve
    from stream import kafka
    from stream.replayer import replay, wait_for_group

    data = demo()
    path = tmp_path / "match.jsonl"
    path.write_text(
        "\n".join(
            [data.match.model_dump_json()]
            + [e.model_dump_json() for e in data.events.items]
        )
    )
    kafka.ensure_topic(kafka.TOPIC)
    group = f"t-{uuid.uuid4().hex[:6]}"
    c = Consumer(
        kafka.config(
            **{
                "group.id": group,
                "enable.auto.commit": False,
                "auto.offset.reset": "latest",
            }
        )
    )
    c.subscribe([kafka.TOPIC])
    sink, out = kafka_sink("overlays"), []
    live = Live(
        client(),
        lambda o: (sink(o), out.append(o)),
        languages=[],
        speed=600,
        policy=fast_policy(),
    )

    async def go():
        served = asyncio.create_task(serve(live, c, exit_on_end=True))
        await asyncio.to_thread(wait_for_group, group)
        await asyncio.to_thread(replay, path, 600)
        await asyncio.wait_for(served, 120)

    asyncio.run(go())
    c.close()
    sink.flush(10)
    assert live.stats.transport_s and live.stats.detect_s
    assert any(o.kind == "recap_full_time" and o.status == "aired" for o in out)
    assert any(o.slot == "narrative" and o.status == "aired" for o in out)
