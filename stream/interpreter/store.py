"""Postgres store for the interpreter: what it has already counted.

Every event is inserted with event_id as the primary key before it touches
MatchState. A second copy of the same event (Kafka redelivery after a
restart, or the same match replayed twice) inserts nothing and is skipped.
On start the interpreter rebuilds each MatchState from the stored events, so
a restart never loses or double-counts anything.
"""

import os

import psycopg
from psycopg.types.json import Jsonb

from core.contracts import Match, MatchEvent, MatchState

SCHEMA = """
create table if not exists interpreter_matches (
    match_id text primary key,
    payload jsonb not null
);
create table if not exists interpreter_events (
    event_id text primary key,
    match_id text not null references interpreter_matches,
    seq bigserial,
    payload jsonb not null
);
create index if not exists interpreter_events_match on interpreter_events (match_id, seq);
create table if not exists match_state (
    match_id text primary key references interpreter_matches,
    state jsonb not null,
    updated_at timestamptz not null default now()
);
"""


def database_url() -> str:
    """DATABASE_URL, or the compose Postgres from PG_* variables."""
    if url := os.environ.get("DATABASE_URL"):
        return url
    from psycopg.conninfo import make_conninfo

    return make_conninfo(
        host=os.environ.get("PG_HOST", "localhost"),
        port=os.environ.get("PG_PORT", "5434"),
        user=os.environ.get("PG_USER", "second_ball"),
        dbname=os.environ.get("PG_DB", "second_ball"),
        password=os.environ.get("PG_PASSWORD", ""),
    )


class Store:
    def __init__(self, url: str | None = None):
        self.conn = psycopg.connect(url or database_url(), autocommit=True)
        with self.conn.transaction():
            self.conn.execute(SCHEMA)

    def close(self):
        self.conn.close()

    def record_match(self, match: Match) -> None:
        self.conn.execute(
            "insert into interpreter_matches values (%s, %s) on conflict do nothing",
            (match.match_id, Jsonb(match.model_dump(mode="json"))),
        )

    def record_event(self, event: MatchEvent) -> bool:
        """True if new; False if this event_id was already counted."""
        cur = self.conn.execute(
            "insert into interpreter_events (event_id, match_id, payload) "
            "values (%s, %s, %s) on conflict (event_id) do nothing",
            (event.event_id, event.match_id, Jsonb(event.model_dump(mode="json"))),
        )
        return cur.rowcount == 1

    def save_state(self, match_id: str, state: MatchState) -> None:
        self.conn.execute(
            "insert into match_state (match_id, state) values (%s, %s) "
            "on conflict (match_id) do update set state = excluded.state, "
            "updated_at = now()",
            (match_id, Jsonb(state.model_dump(mode="json"))),
        )

    def load_state(self, match_id: str) -> MatchState | None:
        row = self.conn.execute(
            "select state from match_state where match_id = %s", (match_id,)
        ).fetchone()
        return MatchState.model_validate(row[0]) if row else None

    def load(self):
        """Every stored match with its events, in the order they were counted."""
        for match_id, payload in self.conn.execute(
            "select match_id, payload from interpreter_matches order by match_id"
        ).fetchall():
            events = self.conn.execute(
                "select payload from interpreter_events where match_id = %s "
                "order by seq",
                (match_id,),
            ).fetchall()
            yield (
                Match.model_validate(payload),
                [MatchEvent.model_validate(p) for (p,) in events],
            )
