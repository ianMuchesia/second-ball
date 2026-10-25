"""Numbers are written by code: same facts for every viewer, persona-specific
display strings, and the Verifier rejects the slips a real run made
(13.0 shots, "0.3 goals", "zero to one", a score the wrong way round)."""

import pytest

from agents.pipeline.facts import task_for
from agents.pipeline.models import Analysis
from agents.pipeline.prompts import values_block
from agents.pipeline.verifier import number_style, verify, wrong_direction
from agents.pipeline.workflow import checked_claim, values_of
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


def goal_88(data):
    return next(m for m in data.moments if m.kind == "goal" and m.clock.minute == 88)


def test_counts_come_phrased_by_code(goal):
    data, _ = goal
    t = task_for(data, goal_88(data), "analyst")
    assert t.display["counter_goals"] == "Harbour's second goal on the counter"
    assert t.display["passes_in_move"] == "1 pass in the move"


@pytest.mark.parametrize(
    ("line", "why"),
    [
        # Aired 24 Oct: the right number attached to the wrong thing.
        (
            (
                "Harbour lead 2-0: a counter-attack behind Riverside's left-back "
                "creates 2 counter goals, adding xG 0.45."
            ),
            "Harbour's second goal on the counter",
        ),
        # The count given to the wrong team, or to no team at all.
        (
            "Riverside's second goal on the counter behind the left-back makes it 0-2.",
            "as given",
        ),
        ("The second counter goal for Riverside; Harbour lead 2-0.", "as given"),
        ("Harbour lead 2-0. A counter creates 2 counter goals.", "as given"),
        # The right goal, the wrong number of passes or counters.
        (
            (
                "Harbour lead 2-0 with their second counter goal from 2 passes "
                "behind Riverside's left-back."
            ),
            "no code-made count of passes is 2",
        ),
        (
            "Harbour lead 2-0 with their third counter goal behind Riverside's left-back.",
            "no code-made count of counters is 3",
        ),
    ],
)
def test_wrong_relations_are_rejected(goal, line, why):
    data, _ = goal
    reasons = verify(line, analysis(data, goal_88(data), "analyst")).reasons
    assert any(why in r for r in reasons), reasons


# Ian, 2026-10-25: the count need not be said in code's exact words; a true
# rewording of whose count it is passes (it was blocked on 24 Oct; the five
# Foundry drafts he labelled false alarms are of this kind).
@pytest.mark.parametrize(
    "line",
    [
        "Harbour lead 2-0, their second counter goal behind the left-back.",
        "Harbour lead 2-0 with their second counter goal, behind Riverside's left-back.",
        "Harbour score their second goal on the counter, 1 pass behind Riverside's left-back.",
        "A second counter goal behind Riverside's left-back, and Harbour lead 2-0.",
        (
            "Harbour's break behind Riverside's left-back brings a second counter "
            "goal: Harbour lead 2-0."
        ),
    ],
)
def test_a_true_rewording_of_the_count_passes(goal, line):
    data, _ = goal
    v = verify(line, analysis(data, goal_88(data), "analyst"))
    assert not any("as given" in r for r in v.reasons), v.reasons


def test_one_is_ordinary_english(goal):
    data, m = goal
    line = "One pass behind Riverside's left-back on the counter, and Harbour lead 1-0!"
    assert verify(line, analysis(data, m, "casual")).passed


def test_a_count_said_as_given_passes(goal):
    data, _ = goal
    line = (
        "Harbour's second goal on the counter, behind Riverside's left-back: "
        "a chance worth xG 0.45. Harbour lead 2-0."
    )
    assert verify(line, analysis(data, goal_88(data), "analyst")).passed


def test_a_claim_on_screen_is_verified_too(goal):
    data, m = goal
    a = analysis(data, m, "casual")
    bad = a.model_copy(
        update={
            "insight": a.insight.model_copy(
                update={"claim": "Harbour scored to take a one-nil lead."}
            )
        }
    )
    # Format is fixed in code ("one-nil" -> "1-0"); a wrong fact is replaced.
    out = checked_claim(bad)
    assert not out.claim_reasons
    assert out.insight.claim == "Harbour scored to take a 1-0 lead."
    wrong = a.model_copy(
        update={
            "insight": a.insight.model_copy(
                update={"claim": "Harbour lead Riverside 0-1 after the counter."}
            )
        }
    )
    out = checked_claim(wrong)
    assert out.claim_reasons and "leader's score goes first" in out.claim_reasons[0]
    assert out.insight.claim.startswith("GOAL, 34'.")
    assert verify(out.insight.claim, out).passed
    # A correct claim is kept, even without the zone a line must name.
    ok = a.model_copy(
        update={
            "insight": a.insight.model_copy(
                update={"claim": "Harbour score on the counter."}
            )
        }
    )
    assert checked_claim(ok).insight.claim == "Harbour score on the counter."
