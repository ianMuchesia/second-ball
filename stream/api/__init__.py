"""Broadcast API: serves run bundles to the screen (judge mode: zero model
calls), live mode over SSE, evidence by event ids, and producer actions with
an append-only audit log.

    uv run uvicorn stream.api:app --port 8000      (RUNS_DIR, default runs/)

Endpoints (all JSON unless noted):
    GET  /api/runs                               bundles on disk
    GET  /api/runs/{run}                         meta, match, moments, overlays,
                                                 narrations, indicators, audit
    GET  /api/runs/{run}/events                  events with freeze frames
    GET  /api/runs/{run}/evidence?ids=a,b        events in plain words + positions
    GET  /api/runs/{run}/traces?trace_id=...     spans of one trace
    GET  /api/runs/{run}/stream?speed=10         SSE: the run replayed in match time
    GET  /api/live                               SSE: match-events + overlays (Kafka)
    GET  /api/registry/{metric}                  a metric's registered definition
    GET  /api/runs/{run}/producer                approval queue, rejected drafts, audit
    POST /api/runs/{run}/producer/{overlay_id}   {action: approve|reject, who, reason}
    POST /api/runs/{run}/inject-test-error       a wrong claim through the real Verifier
"""

import asyncio
import json
import os
import re
import threading
import time
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agents.pipeline.models import Analysis, NarrationTask
from agents.pipeline.verifier import verify
from agents.pipeline.workflow import values_of
from core.contracts import Insight, Match, MatchEvent
from core.metrics import Events, registry
from core.moments import config as moment_config
from stream.api.moves import evidence_of, numbers
from stream.api.words import absolute, describe_event

ROOT = Path(__file__).resolve().parents[2]
RUN_NAME = re.compile(r"^[A-Za-z0-9_-]+$")
TEST_LABEL = "TEST INJECTION: a deliberately wrong line, not an AI output"

app = FastAPI(title="second-ball broadcast API")


def runs_dir() -> Path:
    return Path(os.environ.get("RUNS_DIR", ROOT / "runs"))


def run_path(run: str) -> Path:
    if not RUN_NAME.match(run) or not (runs_dir() / run / "meta.json").exists():
        raise HTTPException(404, f"no run {run!r}")
    return runs_dir() / run


def rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


@lru_cache(maxsize=8)
def bundle(path: Path, stamp: float) -> dict:
    """Parsed once per run (stamp = meta.json mtime, so a re-record reloads)."""
    match = Match.model_validate_json((path / "match.json").read_text())
    events = [MatchEvent.model_validate(r) for r in rows(path / "events.jsonl")]
    # Match seconds on core's continuous clock: the time the Producer and the
    # recorded overlays use, and the screen's playback clock.
    clock = Events.for_match(match, events).elapsed
    return {
        "meta": json.loads((path / "meta.json").read_text()),
        "match": match,
        "events": events,
        "by_id": {e.event_id: e for e in events},
        "index": {e.event_id: i for i, e in enumerate(events)},
        "t": {e.event_id: t for e, t in zip(events, clock, strict=True)},
        "moments": rows(path / "moments.jsonl"),
        "overlays": rows(path / "overlays.jsonl"),
        "narrations": rows(path / "narrations.jsonl"),
        "indicators": rows(path / "indicators.jsonl"),
        "traces": rows(path / "traces.jsonl"),
    }


def load(run: str) -> dict:
    path = run_path(run)
    return bundle(path, (path / "meta.json").stat().st_mtime)


@app.get("/api/runs")
def list_runs():
    d = runs_dir()
    if not d.exists():
        return []
    return [
        json.loads((p / "meta.json").read_text())
        for p in sorted(d.iterdir())
        if (p / "meta.json").exists()
    ]


@app.get("/api/runs/{run}")
def get_run(run: str):
    b = load(run)
    return {
        "meta": b["meta"],
        "match": b["match"].model_dump(mode="json"),
        "moments": [
            {
                **m,
                "t": clock_t(b, m["clock"]),
                # The evidence in two layers (stream/api/moves.py).
                "move": evidence_of(m, b["events"], b["index"]),
                "numbers": numbers(m, b["index"], b["t"]),
            }
            for m in b["moments"]
        ],
        "overlays": [{**o, "t": overlay_t(b, o)} for o in b["overlays"]],
        "narrations": [
            {
                **{k: v for k, v in n.items() if k != "task"},
                # What code knew (facts, counts): the evidence drawer shows them.
                "facts": (n.get("task") or {}).get("facts", {}),
                "counts": (n.get("task") or {}).get("counts", {}),
            }
            for n in b["narrations"]
        ],
        "indicators": b["indicators"],
        "audit": rows(run_path(run) / "audit.jsonl"),
    }


@app.get("/api/runs/{run}/events")
def get_events(run: str):
    b = load(run)
    return [absolute(e, b["match"], b["t"][e.event_id]) for e in b["events"]]


@app.get("/api/runs/{run}/evidence")
def evidence(run: str, ids: str = Query(..., description="comma-separated event ids")):
    b = load(run)
    wanted = [i for i in ids.split(",") if i]
    missing = [i for i in wanted if i not in b["by_id"]]
    if missing:
        raise HTTPException(404, f"unknown event ids: {missing[:5]}")
    return [
        {
            **absolute(b["by_id"][i], b["match"], b["t"][i]),
            "words": describe_event(b["by_id"][i], b["match"]),
        }
        for i in wanted
    ]


@app.get("/api/runs/{run}/traces")
def traces(run: str, trace_id: str):
    return [s for s in load(run)["traces"] if s["trace_id"] == trace_id]


@app.get("/api/registry/{name}")
def metric(name: str):
    try:
        m = registry.get(name)
    except KeyError:
        raise HTTPException(404, f"no metric {name!r}") from None
    return {
        "name": m.name,
        "definition": m.definition,
        "grain": m.grain,
        "unit": m.unit,
        "display_name": m.display_name,
        "formula": m.formula,
    }


@app.get("/api/moment-rules/{kind}")
def moment_rule(kind: str):
    """The detector's rule for a moment kind: its thresholds (core/moments)."""
    rules = moment_config()
    if kind not in rules["importance"]:
        raise HTTPException(404, f"no rule for {kind!r}")
    section = {"repeated_pattern": "counter"}.get(kind, kind)
    return {
        "kind": kind,
        "importance": rules["importance"][kind],
        "thresholds": rules.get(section, {}),
        "source": "core/moments/config.yaml",
    }


# ---- producer -----------------------------------------------------------------


class Action(BaseModel):
    action: Literal["approve", "reject"]
    who: str = Field(min_length=1, max_length=80)
    reason: str = Field(default="", max_length=500)


AUDIT_LOCK = threading.Lock()


def append_audit(run: str, row: dict) -> dict:
    """Append-only: rows are only ever added, never edited or removed."""
    row = {"at": datetime.now(UTC).isoformat(), **row}
    with AUDIT_LOCK, (run_path(run) / "audit.jsonl").open("a") as f:
        f.write(json.dumps(row) + "\n")
    return row


@app.get("/api/runs/{run}/producer")
def producer(run: str):
    b = load(run)
    latest: dict[str, dict] = {}
    for o in b["overlays"]:
        latest[o["overlay_id"]] = o
    queue = [o for o in latest.values() if o["status"] == "pending"]
    drafts = [
        {
            "overlay_id": n["overlay_id"],
            "kind": n["kind"],
            "persona": n["persona"],
            "attempt": i + 1,
            "text": v["text"],
            "reasons": v["reasons"],
            "final_fallback": n["fallback"],
        }
        for n in b["narrations"]
        for i, v in enumerate(n["verdicts"])
        if not v["passed"]
    ]
    return {
        "queue": queue,
        "rejected_drafts": drafts,
        "audit": rows(run_path(run) / "audit.jsonl"),
    }


@app.post("/api/runs/{run}/producer/{overlay_id}")
def act(run: str, overlay_id: str, body: Action):
    if overlay_id not in {o["overlay_id"] for o in load(run)["overlays"]}:
        raise HTTPException(404, f"no overlay {overlay_id!r}")
    return append_audit(
        run,
        {
            "who": body.who,
            "action": body.action,
            "overlay_id": overlay_id,
            "reason": body.reason,
        },
    )


class Injection(BaseModel):
    overlay_id: str | None = None
    who: str = Field(default="producer", min_length=1, max_length=80)


def corrupt(text: str) -> str:
    """A deliberately wrong version of a line: a number changed, or a prediction."""
    m = re.search(r"\d+\.\d+", text)
    if m:
        wrong = f"{float(m.group(0)) + 0.37:.2f}"
        return text[: m.start()] + wrong + text[m.end() :]
    return text.rstrip(".!") + ", and they will win this."


@app.post("/api/runs/{run}/inject-test-error")
def inject(run: str, body: Injection):
    b = load(run)
    made = [n for n in b["narrations"] if n.get("task") and not n["fallback"]]
    if body.overlay_id:
        made = [n for n in made if n["overlay_id"] == body.overlay_id]
    if not made:
        raise HTTPException(404, "no narrated line to test with")
    n = made[0]
    task = NarrationTask.model_validate(n["task"])
    analysis = Analysis(
        task=task, insight=Insight.model_validate(n["insight"]), values=values_of(task)
    )
    original = n["verdicts"][-1]["text"]
    wrong = corrupt(original)
    verdict = verify(wrong, analysis)
    append_audit(
        run,
        {
            "who": body.who,
            "action": "inject_test_error",
            "overlay_id": n["overlay_id"],
            "reason": f"rejected: {verdict.reasons}"
            if not verdict.passed
            else "passed (!)",
        },
    )
    return {
        "label": TEST_LABEL,
        "overlay_id": n["overlay_id"],
        "original": original,
        "injected": wrong,
        "verdict": verdict.model_dump(mode="json"),
    }


# ---- live (SSE) ---------------------------------------------------------------


def sse(kind: str, data) -> str:
    return f"event: {kind}\ndata: {json.dumps(data)}\n\n"


@app.get("/api/runs/{run}/stream")
async def stream_run(
    run: str, speed: float = Query(10, gt=0, le=600), start: float = 0
):
    """The run replayed in match time at `speed`, as server-sent events."""
    b = load(run)
    timeline = [
        (b["t"][e.event_id], "event", absolute(e, b["match"], b["t"][e.event_id]))
        for e in b["events"]
    ]
    timeline += [(overlay_t(b, o), "overlay", o) for o in b["overlays"]]
    timeline.sort(key=lambda x: x[0])

    async def gen():
        t0 = time.monotonic()
        yield sse("meta", b["meta"])
        for t, kind, data in timeline:
            if t < start:
                continue
            wait = (t - start) / speed - (time.monotonic() - t0)
            if wait > 0:
                await asyncio.sleep(wait)
            yield sse(kind, data)
        yield sse("end", {"match_id": b["match"].match_id})

    return StreamingResponse(gen(), media_type="text/event-stream")


def overlay_t(b: dict, o: dict) -> float:
    """When an overlay went out in the run; older bundles: its clock."""
    return (
        o["aired_t"] if o.get("aired_t") is not None else clock_t(b, o["t_in"]["match"])
    )


def clock_t(b: dict, c: dict) -> float:
    """Match seconds (core's clock) of a match clock: its first event at or after."""
    key = (c["period"], c["minute"], c["second"])
    return next(
        (
            b["t"][e.event_id]
            for e in b["events"]
            if (e.period, e.minute, e.second) >= key
        ),
        b["t"][b["events"][-1].event_id],
    )


@app.get("/api/live")
async def live(topics: str = "match-events,overlays"):
    """match-events and overlays from Kafka as they happen (needs make up and
    `make live`)."""
    from confluent_kafka import Consumer

    from stream import kafka

    q: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()
    stop = threading.Event()

    def consume():
        c = Consumer(
            kafka.config(
                **{
                    "group.id": f"screen-{os.getpid()}-{time.monotonic_ns()}",
                    "auto.offset.reset": "latest",
                    "enable.auto.commit": False,
                }
            )
        )
        c.subscribe(topics.split(","))
        try:
            while not stop.is_set():
                msg = c.poll(0.2)
                if msg is None or msg.error():
                    continue
                contract = (kafka.header(msg, "contract") or b"").decode()
                loop.call_soon_threadsafe(
                    q.put_nowait, (contract, json.loads(msg.value()))
                )
        finally:
            c.close()

    threading.Thread(target=consume, daemon=True).start()

    async def gen():
        try:
            yield sse("ready", {"topics": topics})
            while True:
                contract, data = await q.get()
                yield sse(contract or "message", data)
        finally:
            stop.set()

    return StreamingResponse(gen(), media_type="text/event-stream")


# The built screen, if present (npm run build), served at /.
DIST = ROOT / "web" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def index(path: str):
        """The screen's routes (/runs/demo, ...) are the app's, not files."""
        if path.startswith("api/"):
            raise HTTPException(404)
        return FileResponse(DIST / "index.html")
