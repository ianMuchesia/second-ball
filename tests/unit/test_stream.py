"""Replayer -> Kafka -> interpreter -> Postgres, end to end on the demo match."""

import threading
import time
import uuid
from pathlib import Path

import pytest

from core.metrics import Events, match_state
from engine.generate import main as generate
from stream import kafka
from stream.interpreter import Interpreter, consumer, run
from stream.interpreter.store import Store
from stream.replayer import delays, read, replay


@pytest.fixture(scope="module")
def demo_file(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("demo")
    generate(["--demo", "--out", str(out)])
    return out / "match.jsonl"


@pytest.fixture
def topic(kafka_env):
    name = f"match-events-{uuid.uuid4().hex[:8]}"
    kafka.ensure_topic(name)
    return name


def expected(path):
    match, events = read(path)
    return match, match_state(Events.for_match(match, events))


def test_delays_follow_match_time_and_skip_half_time(demo_file):
    _, events = read(demo_file)
    d = delays(events)
    assert d[0] == 0 and all(x >= 0 for x in d)
    first_h2 = next(i for i, e in enumerate(events) if e.period == 2)
    assert d[first_h2] == 0


def test_restart_and_second_replay_never_double_count(demo_file, topic, database_url):
    match, want = expected(demo_file)
    n_events = len(read(demo_file)[1])
    replay(demo_file, float("inf"), topic)

    # First interpreter counts part of the match, then "crashes".
    store = Store(database_url)
    c = consumer(f"g-{uuid.uuid4().hex[:6]}", topic)
    handled, _ = run(Interpreter(store), c, stop_after=700, idle_s=30)
    assert handled == 700
    c.close()
    store.close()

    # Restart: state is rebuilt from Postgres, and a new consumer group reads
    # the whole topic again from the start; every repeat must be skipped.
    store = Store(database_url)
    interp = Interpreter(store)
    assert len(interp.matches[match.match_id].items) == 699  # 700 minus the Match
    c = consumer(f"g-{uuid.uuid4().hex[:6]}", topic)
    run(interp, c, until_end=match.match_id, idle_s=30)
    first = store.load_state(match.match_id)
    assert first == want
    assert len(interp.latencies_s) == n_events - 699  # only new events counted

    # The same match replayed a second time changes nothing.
    replay(demo_file, float("inf"), topic)
    run(interp, c, until_end=match.match_id, idle_s=30)
    c.close()
    assert store.load_state(match.match_id) == want
    assert len(interp.matches[match.match_id].items) == n_events
    store.close()


def test_latency_under_one_second_at_60x(demo_file, topic, database_url):
    match, want = expected(demo_file)
    store = Store(database_url)
    interp = Interpreter(store)
    c = consumer(f"g-{uuid.uuid4().hex[:6]}", topic)
    # Join the group before the replay starts, so latency is not start-up time.
    deadline = time.monotonic() + 30
    while not c.assignment() and time.monotonic() < deadline:
        c.poll(0.2)
    assert c.assignment()
    sender = threading.Thread(target=replay, args=(demo_file, 60, topic))
    sender.start()
    run(interp, c, until_end=match.match_id, idle_s=60)
    sender.join()
    c.close()
    lat = sorted(interp.latencies_s)
    assert len(lat) == len(read(demo_file)[1])
    assert lat[-1] < 1.0, f"max latency {lat[-1]:.3f}s"
    assert store.load_state(match.match_id) == want
    store.close()
