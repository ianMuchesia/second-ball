"""Code templates: broadcast sentences per kind and persona, English and
Kiswahili, built only from code values, checked by the Verifier; and a goal's
xG is never circular (the goal's own chance is not in a before/after change)."""

import asyncio

import pytest

from agents.live.record import fake_llm
from agents.pipeline.facts import task_for
from agents.pipeline.models import Analysis
from agents.pipeline.templates import template
from agents.pipeline.verifier import numbers, untranslated, verify
from agents.pipeline.workflow import narrate, values_of
from core.contracts import Insight
from tests.unit.test_narration_report import demo


@pytest.fixture(scope="module")
def data():
    return demo()


def analysis(data, moment, persona):
    t = task_for(data, moment, persona)
    insight = Insight(
        claim="x",
        mechanism="y",
        evidence_event_ids=moment.evidence_event_ids,
        confidence=1.0,
    )
    return Analysis(task=t, insight=insight, values=values_of(t))


def goal_34(data):
    return next(m for m in data.moments if m.kind == "goal" and m.clock.minute == 34)


def test_a_goals_xg_is_not_circular(data):
    """34': 0.162 -> 0.612 was the goal's own 0.45. Now: xG before the move,
    and the chance as its own number."""
    m = goal_34(data)
    assert set(m.metrics_after) == {"shot_xg"}
    assert m.metrics_after["shot_xg"].value == pytest.approx(0.45)
    assert m.metrics_before["xg"].value == pytest.approx(0.162, abs=0.001)
    shot = data.events.items[data.by_id[m.evidence_event_ids[-1]]]
    assert shot.event_id not in m.metrics_before["xg"].evidence_event_ids


def test_the_34th_minute_goal_reads_like_a_broadcast(data):
    m = goal_34(data)
    assert template(analysis(data, m, "casual")) == (
        "GOAL, 34'. Harbour score on the counter, in behind Riverside's "
        "left-back. Harbour lead 1-0."
    )
    analyst = template(analysis(data, m, "analyst"))
    assert "a chance worth xG 0.45 (xG 0.16 before the move)" in analyst
    sw = template(analysis(data, m, "casual"), "sw")
    assert sw.startswith("GOLI, dakika ya 34. Harbour wanafunga")
    assert "Harbour wanaongoza 1-0" in sw


def test_every_template_passes_the_verifier_in_both_languages(data):
    for m in data.moments:
        for persona in ("casual", "analyst"):
            a = analysis(data, m, persona)
            en, sw = template(a, "en"), template(a, "sw")
            assert verify(en, a).passed, (m.kind, persona, en, verify(en, a).reasons)
            assert untranslated(sw, en) is None, (m.kind, sw)
            # Kiswahili quotes only the English template's numbers.
            assert {x for x, _, _ in numbers(sw)} <= {x for x, _, _ in numbers(en)} | {
                float(m.clock.minute),
                *map(float, a.task.context.score),
                *(float(p.shirt_number) for p in a.task.context.lineup),
            }, (m.kind, sw)


def test_when_the_model_is_down_the_template_airs_in_kiswahili_too(data):
    llm = fake_llm()
    llm.killed = True  # quota gone: no model calls at all
    task = task_for(data, goal_34(data), "casual", ["sw"])
    out = asyncio.run(narrate(llm, task))
    assert out.fallback
    a = analysis(data, goal_34(data), "casual")
    assert out.overlay.text == {"en": template(a, "en"), "sw": template(a, "sw")}
    assert llm.budget.ledger == []
