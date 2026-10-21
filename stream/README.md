# stream

Phase 2a: replayer and interpreter. Events only, no model on this path.

```
match.jsonl --replayer--> Kafka topic match-events --interpreter--> MatchState (Postgres)
               1x/10x/60x     key = match_id            dedupe on event_id
```

- **Replayer** (`python -m stream.replayer FILE --speed 10`): sends the Match, each
  event when its match time comes, then a `MatchEnd` marker. Header `contract`
  says which; header `sent_at_ns` is for latency.
- **Interpreter** (`python -m stream.interpreter`): stores each event in
  Postgres with `event_id` as primary key *before* counting it, then commits
  the Kafka offset. A repeat (redelivery after a restart, or the same match
  replayed twice) inserts nothing and is skipped. On start it rebuilds every
  MatchState from the stored events.
- **Numbers** come only from `core/metrics` (the registry); each carries the
  event ids that produced it. Windows: whole match, last 5, 10, 15 minutes.
- **Config** is env vars only (`stream/kafka.py`): local Kafka now, Azure Event
  Hubs' Kafka endpoint later.

```sh
make up                              # Kafka + Postgres (needs PG_PASSWORD in .env)
make replay MATCH=demo SPEED=10      # ~10 min; timeline -> docs/timelines/demo.png
```

Tests (`tests/unit/test_stream.py`) start throwaway Kafka and Postgres
containers with Docker, or use `TEST_KAFKA_BOOTSTRAP` / `TEST_DATABASE_URL`
(CI services).
