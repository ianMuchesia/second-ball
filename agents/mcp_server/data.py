"""Where the MCP server's numbers come from: one match's events, read-only.

Two sources, same contract:
- a match file (JSONL: Match, then MatchEvents), for local runs and tests;
- the interpreter's Postgres, in a READ ONLY session (writes are refused by
  the database itself, not just by our code).

Moments are recomputed with core.moments from the events (deterministic), so
the server never needs anything but events.
"""

from functools import cached_property
from pathlib import Path

import psycopg

from core.contracts import Match, MatchEvent, Moment
from core.metrics import Events
from core.moments import detect


class MatchData:
    def __init__(self, match: Match, events: list[MatchEvent]):
        self.match = match
        self.events = Events.for_match(match, events)
        self.by_id = {e.event_id: k for k, e in enumerate(self.events.items)}

    @cached_property
    def moments(self) -> list[Moment]:
        return detect(self.events)

    @classmethod
    def from_file(cls, path: Path) -> "MatchData":
        lines = Path(path).read_text().splitlines()
        return cls(
            Match.model_validate_json(lines[0]),
            [MatchEvent.model_validate_json(x) for x in lines[1:] if x],
        )

    @classmethod
    def from_postgres(cls, url: str, match_id: str | None = None) -> "MatchData":
        """Latest match (or `match_id`) from the interpreter's tables."""
        with read_only(url) as conn:
            if match_id is None:
                row = conn.execute(
                    "select m.match_id from interpreter_matches m "
                    "join interpreter_events e using (match_id) "
                    "group by m.match_id order by max(e.seq) desc limit 1"
                ).fetchone()
                if row is None:
                    raise LookupError("no match in the interpreter's store yet")
                match_id = row[0]
            payload = conn.execute(
                "select payload from interpreter_matches where match_id = %s",
                (match_id,),
            ).fetchone()
            if payload is None:
                raise LookupError(f"unknown match {match_id}")
            events = conn.execute(
                "select payload from interpreter_events where match_id = %s order by seq",
                (match_id,),
            ).fetchall()
        return cls(
            Match.model_validate(payload[0]),
            [MatchEvent.model_validate(p) for (p,) in events],
        )


def read_only(url: str) -> psycopg.Connection:
    """A connection whose every transaction is READ ONLY."""
    conn = psycopg.connect(url, autocommit=True)
    conn.execute("set session characteristics as transaction read only")
    return conn
