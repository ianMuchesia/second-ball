"""Numbers are written by code: same facts for every viewer, persona-specific
display strings, and the Verifier rejects the slips a real run made
(13.0 shots, "0.3 goals", "zero to one", a score the wrong way round)."""

import pytest

from agents.pipeline.facts import task_for
from agents.pipeline.models import Analysis
from agents.pipeline.prompts import values_block
from agents.pipeline.verifier import number_style, verify, wrong_direction
from agents.pipeline.workflow import values_of
from core.contracts import Insight
from tests.unit.test_narration_report import demo


@pytest.fixture(scope="module")
def goal():
    data = demo()
    return data, next(m for m in data.moments if m.kind == "goal")


def analysis(data, moment, persona):
    t = task_for(data, moment, persona)
    insight = Insight(
        claim="goal",
        mechanism="counter",
        evidence_event_ids=t.moment.evidence_event_ids,
        confidence=1.0,
    )
    return Analysis(task=t, insight=insight, values=values_of(t))


def test_same_facts_for_every_viewer_only_the_writing_differs(goal):
    data, m = goal
    fan, analyst = task_for(data, m, "casual"), task_for(data, m, "analyst")
    assert fan.facts == analyst.facts and fan.counts == analyst.counts
    assert fan.display["score"] == analyst.display["score"] == "Riverside 0-1 Harbour"
    assert fan.display["standing"] == "Harbour lead 1-0"
    assert analyst.display["chance"] == "xG 0.45"
    assert fan.display["chance"] == "a big chance"


def test_the_model_sees_counts_as_whole_numbers(goal):
    data, m = goal
    a = analysis(data, m, "analyst")
    block = values_block(a.task, a.values | {"shots": 13.0})
    assert '"shots": 13,' in block or '"shots": 13}' in block
    assert '"say": {"score": "Riverside 0-1 Harbour"' in block


@pytest.mark.parametrize(
    ("line", "why"),
    [
        ("Harbour lead 1-0 despite 3.0 shots.", "whole numbers"),
        ("Harbour leads Riverside zero to one at the half.", "digits"),
        ("Riverside create an 0.3 goals chance.", "xG 0.30"),
        ("Riverside 1-0 Harbour at the break.", "wrong way round"),
        ("Harbour lead 0-1 at the break.", "leader's score goes first"),
    ],
)
def test_the_verifier_rejects_badly_written_numbers(goal, line, why):
    data, m = goal
    reasons = verify(line, analysis(data, m, "analyst")).reasons
    assert any(why in r for r in reasons), reasons


@pytest.mark.parametrize(
    "line",
    [
        "Harbour lead 1-0 after a counter.",
        "Riverside 0-1 Harbour: a counter worth xG 0.45.",
        "Harbour 1-0 Riverside after the break.",
    ],
)
def test_well_written_numbers_pass(goal, line):
    data, m = goal
    assert number_style(line, analysis(data, m, "analyst")) == []


@pytest.mark.parametrize(
    ("line", "ok"),
    [
        # Aired in the 23 Oct Gemini recording: control ROSE 0.71 -> 0.80.
        ("Riverside drop control from 0.71 to 0.80 after the red card.", False),
        ("Riverside's control rises from 0.71 to 0.80 after the red card.", True),
        ("Pressure on the ball falls from 0.52 to 0.25.", True),
        ("Pressure on the ball climbs from 0.52 to 0.25.", False),
        ("Harbour's xG rose from 0.16 to 0.61.", True),
    ],
)
def test_the_direction_word_must_agree_with_the_numbers(line, ok):
    assert (not wrong_direction(line)) is ok
