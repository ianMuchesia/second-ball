"""Record a run: the full pipeline once over a match, saved as a run bundle.

    make record MATCH=demo                    # the free fake model
    make record MATCH=demo PROVIDER=gemini    # a real model: estimate, then asks
    uv run python -m agents.live.record --out runs/e2e

The bundle (runs/<name>/) holds everything the screen needs, so judge mode
plays it back with zero model calls:

    meta.json          model, languages, cost, how it was recorded
    match.json         the Match (team sheets included)
    events.jsonl       every MatchEvent, with freeze frames
    moments.jsonl      every Moment the detector fired
    overlays.jsonl     every overlay status change (all personas, languages),
                       with aired_t: match seconds when it went out
    narrations.jsonl   per line: verdicts incl. rejected drafts, the insight,
                       wall-clock latency and whether it met the 8 s target
    indicators.jsonl   control / openness / momentum each match minute
    traces.jsonl       every span (one trace per moment)

Recorded offline: the match waits for each line, so what airs is what the
pipeline makes; the latency per line is the real wall time it took.
"""

import argparse
import asyncio
import json
import os
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path

from agents.live import Live
from agents.llm import LLMClient, from_env
from agents.llm.fake import FAKE_MODEL, FakeProvider
from agents.llm.guard import add_flags, confirm, match_requests
from agents.llm.prices import PRICES
from agents.mcp_server.data import MatchData
from agents.telemetry import RECORDER, setup
from core.budget import Budget
from core.metrics import Events, registry
from evals.gold import caught

# Shipped languages: a fluent speaker reviewed them (English, Kiswahili).
# Others work in the pipeline but are machine-translated, not reviewed.
SHIPPED = [x for x in os.environ.get("SHIPPED_LANGUAGES", "en,sw").split(",") if x]
INDICATORS = [  # (metric, window in minutes, grain)
    ("control_index", 10, "team"),
    ("openness_index", 10, "match"),
    ("momentum", None, "match"),
]


def fake_llm() -> LLMClient:
    budget = Budget(
        usd_limit=1.0,
        token_limit=10_000_000,
        run_id="record-fake",
        prices=PRICES,
        kes_rate=130,
        kes_rate_date="2026-09-29",
    )
    return LLMClient(FakeProvider(), budget)


def indicators(match, items) -> list[dict]:
    """The side panel's three numbers at the end of each match minute."""
    events = Events.for_match(match)
    out, minute = [], None
    for e in items:
        events.append(e)
        if (e.period, e.minute) == minute:
            continue
        minute = (e.period, e.minute)
        row = {"period": e.period, "minute": e.minute, "t": events.elapsed[-1]}
        for name, window, grain in INDICATORS:
            m = registry.get(name)
            owners = [match.home_team, match.away_team] if grain == "team" else [None]
            for team in owners:
                v = m.compute(events, team, window)
                key = name if team is None else f"{name}.{team}"
                row[key] = (
                    None
                    if v is None
                    else {
                        "value": v.value,
                        "evidence_event_ids": v.evidence_event_ids[-30:],
                    }
                )
        out.append(row)
    return out


def span_row(s) -> dict:
    return {
        "name": s.name,
        "trace_id": f"{s.context.trace_id:032x}",
        "span_id": f"{s.context.span_id:016x}",
        "parent_id": f"{s.parent.span_id:016x}" if s.parent else None,
        "start_ns": s.start_time,
        "end_ns": s.end_time,
        "attributes": {
            k: list(v) if isinstance(v, tuple) else v for k, v in s.attributes.items()
        },
    }


def jsonl(path: Path, rows) -> None:
    with path.open("w") as f:
        for r in rows:
            f.write((r if isinstance(r, str) else json.dumps(r)) + "\n")


async def play(live: Live, data: MatchData) -> None:
    worker = asyncio.create_task(live.worker())
    live.on_match(data.match)
    for e in data.events.items:
        live.on_event(e)
        await live.drain()
    live.on_end(data.match.match_id)
    await live.drain()
    worker.cancel()


def record(match_file: Path, out: Path, llm: LLMClient, languages=None) -> Path:
    setup()
    RECORDER.clear()
    languages = [x for x in (languages or SHIPPED) if x != "en"]
    data = MatchData.from_file(match_file)
    overlays: list[str] = []

    def publish(o):
        # When it really went out in the run (match seconds): a red card's
        # impact fires minutes after the card, so its own clock is not when it aired.
        row = json.loads(o.model_dump_json())
        row["aired_t"] = live.games[o.match_id].now
        overlays.append(json.dumps(row))

    live = Live(llm, publish, languages=languages, speed=1)
    start = time.monotonic()
    asyncio.run(play(live, data))
    if out.exists():  # a re-record is a new run: new bundle, new audit log
        shutil.rmtree(out)
    out.mkdir(parents=True)
    (out / "match.json").write_text(data.match.model_dump_json(indent=1))
    jsonl(out / "events.jsonl", (e.model_dump_json() for e in data.events.items))
    jsonl(
        out / "moments.jsonl",
        (m.model_dump_json() for g in live.games.values() for m in g.moments),
    )
    jsonl(out / "overlays.jsonl", overlays)
    jsonl(out / "narrations.jsonl", live.records)
    jsonl(out / "indicators.jsonl", indicators(data.match, data.events.items))
    jsonl(out / "traces.jsonl", (span_row(s) for s in RECORDER.spans))
    b = llm.budget
    meta = {
        "name": out.name,
        "match_id": data.match.match_id,
        "mode": data.match.mode,
        "recorded_at": datetime.now(UTC).isoformat(),
        "model": llm.provider.model,
        "languages": ["en", *languages],
        "shipped_languages": SHIPPED,
        "model_calls": len(b.ledger),
        "usd": round(b.usd_spent, 6),
        "kes": round(sum(r.get("kes") or 0 for r in b.ledger), 4),
        "wall_s": round(time.monotonic() - start, 1),
        "how": "offline: the match waited for each line; latency is real wall time",
        "outcomes": dict(live.stats.outcomes),
        # What the bundle holds: lines the model wrote and the Verifier passed,
        # and code templates (model failed, out of quota, or rejected 3 times).
        "ai_lines": sum(1 for r in live.records if not r["fallback"]),
        "template_lines": sum(1 for r in live.records if r["fallback"]),
        # True if the budget or the model's quota stopped all model calls.
        "kill_switch": llm.killed,
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=1))
    (out / "audit.jsonl").touch()  # the producer's log for this run, append-only
    return out


def main(argv=None):
    from dotenv import load_dotenv

    load_dotenv()
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--match-file", type=Path, default=Path("demo/match.jsonl"))
    p.add_argument("--out", type=Path, default=Path("runs/demo"))
    p.add_argument("--fake", action="store_true", help="same as --provider fake")
    p.add_argument(
        "--force", action="store_true", help="replace a real-model bundle with fake"
    )
    p.add_argument("--languages", help="comma list; default SHIPPED_LANGUAGES")
    add_flags(p)
    args = p.parse_args(argv)
    if args.fake:
        args.provider = "fake"
    langs = args.languages.split(",") if args.languages else None
    old = args.out / "meta.json"
    if args.provider == "fake" and old.exists() and not args.force:
        was = json.loads(old.read_text()).get("model")
        if was != FAKE_MODEL:
            raise SystemExit(
                f"{args.out} was recorded with {was}: a fake run would replace it. "
                "Use another --out (make record RUN=...), or --force."
            )
    llm = fake_llm() if args.provider == "fake" else from_env(provider=args.provider)
    if args.provider != "fake":
        n = match_requests(args.match_file, langs)
        confirm(
            llm,
            f"About {n} requests (a free dry run of this match made {n}; "
            f"Verifier retries can add more)",
            args.yes,
        )
    out = record(args.match_file, args.out, llm, langs)
    meta = json.loads((out / "meta.json").read_text())
    print(json.dumps(meta))
    # Every draft the Verifier caught is a gold eval item (real mistakes).
    saved = caught.save(out)
    if saved:
        print(f"caught drafts saved: {saved}")
    if args.provider != "fake" and meta["ai_lines"] == 0:
        raise SystemExit(
            f"WARNING: {out} has no AI lines, only templates"
            + (
                " (the budget or the model's quota stopped every call)"
                if meta["kill_switch"]
                else ""
            )
            + ". Re-record when the model is available."
        )


if __name__ == "__main__":
    main()
