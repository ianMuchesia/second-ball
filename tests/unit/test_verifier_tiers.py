"""Verifier tiers, checked against Ian's labels on real caught drafts.

Truth rules block and retry; format rules are fixed in code (no retry);
tone is only noted. The labelled gold set (evals/gold/caught/) is the test:
no false alarms, and every real error blocked for the right reason,
including the four Ian found the Verifier had missed (#10, #16, #17, #18).
"""

import logging

import pytest

from agents.pipeline.facts import task_for
from agents.pipeline.models import Analysis
from agents.pipeline.verifier import check, normalise, verify
from agents.pipeline.workflow import values_of
from core.contracts import Insight
from evals.gold.verifier_eval import right_reason
from evals.gold.verifier_eval import run as gold
from tests.unit.test_narration_report import demo


@pytest.fixture(scope="module")
def checked():
    logging.disable(logging.WARNING)
    try:
        return gold()[0]
    finally:
        logging.disable(logging.NOTSET)


def test_no_false_alarms_on_the_labelled_drafts(checked):
    alarms = [i.row["text"] for i, v in checked if not v.passed and not i.should_block]
    assert alarms == []


def test_every_real_error_is_blocked_for_the_right_reason(checked):
    missed = [
        (i.row["minute"], i.row["text"][:60], v.reasons)
        for i, v in checked
        if i.should_block and not right_reason(i, v)
    ]
    assert missed == []


@pytest.mark.parametrize("n", [10, 16, 17, 18])
def test_the_four_misses_ian_found_are_now_caught(checked, n):
    item, verdict = checked[n - 1]
    assert item.row["missed"] and not verdict.passed
    assert right_reason(item, verdict), verdict.reasons


# ---- the tiers on single lines -----------------------------------------------


@pytest.fixture(scope="module")
def data():
    return demo()


def analysis(data, minute, kind="goal", persona="analyst"):
    m = next(x for x in data.moments if x.kind == kind and x.clock.minute == minute)
    t = task_for(data, m, persona, [])
    insight = Insight(
        claim="x", mechanism="y", evidence_event_ids=m.evidence_event_ids, confidence=1
    )
    return Analysis(task=t, insight=insight, values=values_of(t))


def test_format_is_fixed_in_code_not_blocked(data):
    a = analysis(data, 88)
    v = check(
        "Harbour beat Riverside two-nil on the counter behind Riverside's left-back.", a
    )
    assert v.passed
    assert (
        v.text
        == "Harbour beat Riverside 2-0 on the counter behind Riverside's left-back."
    )
    v = check(
        "Harbour defeated Riverside 0-2 on the counter behind Riverside's left-back.", a
    )
    assert v.passed and "2-0" in v.text and v.fixes
    text, fixes = normalise("Harbour took 13.0 shots, a chance worth xG 1.0.", a)
    assert text == "Harbour took 13 shots, a chance worth xG 1.0." and fixes


def test_an_ambiguous_score_still_blocks(data):
    a = analysis(data, 34)
    # "Harbour lead ... 0-1" says Harbour lead with nothing: a truth error.
    assert not check(
        "Harbour lead Riverside 0-1 on the counter behind Riverside's left-back.", a
    ).passed
    assert not check(
        "Harbour lead zero to one on the counter behind Riverside's left-back.", a
    ).passed


def test_predictions_only_before_full_time(data):
    a = analysis(data, 88)
    assert not verify(
        "Harbour seal it on the counter behind Riverside's left-back, 2-0.", a
    ).passed
    assert not verify(
        "Harbour will seal a 2-0 victory on the counter behind Riverside's left-back.",
        a,
    ).passed
    assert verify(
        "Harbour seal a 2-0 victory on the counter behind Riverside's left-back.",
        a,
        final=True,
    ).passed


def test_a_sentence_may_start_with_an_ordinary_word(data):
    a = analysis(data, 30, "big_chance", "casual")
    assert verify(
        "Patient passing from Riverside: a big chance, level at 0-0.", a
    ).passed
    assert verify("Meanwhile Riverside go close, level at 0-0.", a).passed
    # A name it does not know still blocks, at the start or later.
    assert not verify("Kestrel goes close for Riverside, level at 0-0.", a).passed
    assert not verify("Riverside go close through Okafor, level at 0-0.", a).passed


def test_tone_is_noted_not_blocked(data):
    a = analysis(data, 88)
    v = verify(
        "Harbour strike on the counter behind Riverside's left-back to make it "
        "Riverside 0-2 Harbour, and Harbour lead 2-0!",
        a,
    )
    assert v.passed and "give the score once" in v.notes[0]
