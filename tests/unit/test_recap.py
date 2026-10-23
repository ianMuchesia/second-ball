"""Half-time and full-time recaps: only aired lines and stats, verified."""

import asyncio

from agents.llm.fake import FakeProvider
from agents.pipeline.facts import context_at, task_for
from agents.pipeline.producer import Producer
from agents.pipeline.recap import Aired, recap, recap_task
from agents.pipeline.verifier import verify
from agents.pipeline.workflow import narrate
from tests.unit.test_narration_report import demo
from tests.unit.test_resilience import client, fast_policy

DATA = demo()
GOALS = [m for m in DATA.moments if m.kind == "goal"]


def aired(persona="analyst"):
    llm = client()
    out = []
    for m in GOALS:
        task = task_for(DATA, m, persona, [])
        n = asyncio.run(narrate(llm, task, fast_policy()))
        out.append(Aired(n.overlay.model_copy(update={"status": "aired"}), task))
    return out


def full_time(llm, persona="analyst", languages=()):
    ctx = context_at(DATA, GOALS[-1])
    return asyncio.run(
        recap(
            llm,
            "full_time",
            DATA.events,
            ctx,
            aired(persona),
            persona,
            list(languages),
            fast_policy(),
        )
    )


def test_full_time_recap_is_verified_and_has_evidence():
    out = full_time(client())
    o = out.overlay
    assert o.slot == "recap" and o.kind == "recap_full_time"
    assert not out.fallback and out.verdicts[-1].passed
    assert "harbour_xg" in o.values and o.evidence_event_ids


def test_recap_may_quote_aired_lines_and_stats_but_nothing_else():
    ctx = context_at(DATA, GOALS[-1])
    task, values = recap_task("full_time", DATA.events, ctx, aired(), "analyst", [])
    from agents.pipeline.models import Analysis
    from core.contracts import Insight

    a = Analysis(
        task=task,
        insight=Insight(
            claim="-",
            mechanism="-",
            evidence_event_ids=task.moment.evidence_event_ids,
            confidence=1,
        ),
        values=values,
    )
    xg = values["harbour_xg"]
    ok = f"Full-time: Riverside 0-2 Harbour, Harbour's xG {xg:.2f}. Harbour sealed it."
    assert verify(ok, a, max_words=60, final=True).passed
    assert not verify("Harbour had 9.99 xG.", a, max_words=60, final=True).passed
    # Half-time rules: "sealed it" is a prediction while the clock runs.
    assert not verify("Harbour sealed it.", a, max_words=60).passed


def test_a_recap_that_keeps_failing_falls_back_to_a_code_recap():
    llm = client(
        script=lambda p, s: (
            "Harbour scored 7 goals." if "RECAP" in s else FakeProvider().answer(p, s)
        )
    )
    out = full_time(llm)
    assert out.fallback and len(out.verdicts) == 3
    assert out.overlay.text["en"].startswith("FULL-TIME. Riverside 0-2 Harbour. xG:")


def test_casual_recap_fallback_has_no_decimals():
    llm = client(failures={"recap": ["bad_request"]})
    out = full_time(llm, "casual")
    assert out.fallback and "Shots:" in out.overlay.text["en"]
    assert "." not in out.overlay.text["en"].split("Shots:")[1].split(".")[0]


def test_recap_is_translated_and_airs_at_once():
    out = full_time(client(), languages=["sw"])
    assert set(out.overlay.text) == {"en", "sw"}
    (shown,) = Producer(speed=10).offer(out.overlay, 5400, 1.0, now=5400)
    assert shown.status == "aired"
