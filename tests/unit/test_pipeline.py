"""Narration pipeline with the FAKE model: Verifier, retries, fallback,
Localizer and Producer. No network, no cost."""

import asyncio

import pytest
from agent_framework import Workflow

from agents.llm import LLMClient
from agents.llm.fake import FakeProvider
from agents.llm.prices import PRICES
from agents.pipeline import prompts
from agents.pipeline.models import Analysis, MatchContext, NarrationTask
from agents.pipeline.producer import Producer, stat_card
from agents.pipeline.verifier import verify
from agents.pipeline.workflow import build, narrate, values_of
from core.budget import Budget
from core.contracts import Clock, Insight, MetricValue, Moment

R, HT = "riverside_athletic", "harbour_town"
EV = ["m-e1", "m-e2"]


def mv(v):
    return MetricValue(value=v, evidence_event_ids=EV)


MOMENT = Moment(
    moment_id="m-mo007",
    kind="red_card_impact",
    team=R,
    clock=Clock(period=2, minute=63, second=10),
    importance=0.9,
    metrics_before={"control_index": mv(0.712), "pressure_on_ball": mv(0.52)},
    metrics_after={"control_index": mv(0.805), "pressure_on_ball": mv(0.245)},
    evidence_event_ids=EV,
)
CONTEXT = MatchContext(
    match_id="m",
    home=R,
    away=HT,
    team_names={R: "Riverside", HT: "Harbour"},
    score=(0, 1),
    minute=73,
    players={f"{R}-9": "Ada Brook", f"{HT}-11": "Juma Reed"},
)
TASK = NarrationTask(moment=MOMENT, context=CONTEXT, persona="casual")


def analysis(task=TASK):
    return Analysis(
        task=task,
        insight=Insight(
            claim="x", mechanism="y", evidence_event_ids=EV, confidence=0.5
        ),
        values=values_of(task),
    )


def llm(**fake):
    budget = Budget(
        usd_limit=0.10,
        token_limit=100_000,
        run_id="test",
        prices=PRICES,
        kes_rate=130,
        kes_rate_date="2026-09-29",
    )
    return LLMClient(FakeProvider(**fake), budget)


def run(client, task=TASK):
    return asyncio.run(narrate(client, task))


# ---- Verifier (code) ------------------------------------------------------------


def test_values_come_from_the_moment_not_a_model():
    assert values_of(TASK) == {
        "control_index_before": 0.712,
        "pressure_on_ball_before": 0.52,
        "control_index_after": 0.805,
        "pressure_on_ball_after": 0.245,
    }


@pytest.mark.parametrize(
    "line",
    [
        "Riverside's control went from 0.71 to 0.81.",
        "Control up to 81% for Riverside.",  # a share as a percentage
        "Ten men, 0-1 down at 73', and Ada Brook still pushing.",  # context
        "Riverside's number 9 drives on.",  # a shirt on the pitch
    ],
)
def test_true_lines_pass(line):
    assert verify(line, analysis()).passed, verify(line, analysis()).reasons


def test_wrong_number_is_rejected_with_the_allowed_values():
    v = verify("Riverside's control went up to 0.9.", analysis())
    assert not v.passed and "number 0.9" in v.reasons[0]
    assert "control_index_after=0.805" in v.reasons[0]


def test_invented_player_is_rejected_even_at_the_start():
    for line in ["Okafor makes it happen.", "What a run from Okafor."]:
        v = verify(line, analysis())
        assert not v.passed and "'Okafor'" in v.reasons[0]


def test_prediction_is_rejected():
    v = verify("Riverside will win this, you watch.", analysis())
    assert not v.passed and "no predictions" in v.reasons[0]


def test_blaming_the_weather_is_rejected():
    v = verify("Because of the rain the ball skidded past him.", analysis())
    assert not v.passed and "weather" in v.reasons[0]


def test_referee_or_injury_talk_needs_a_human():
    v = verify("Harbour want a decision from the referee.", analysis())
    assert v.passed and v.risk_tier == "high"


# ---- workflow with the fake model --------------------------------------------------


def test_workflow_is_agent_framework():
    assert isinstance(build(llm()), Workflow)


def test_clean_line_passes_first_time():
    out = run(llm())
    assert (out.attempts, out.fallback) == (1, False)
    assert out.overlay.status == "pending" and out.overlay.text["en"]
    assert out.overlay.evidence_event_ids == EV


def test_planted_wrong_number_is_rejected_then_retried_and_passes():
    out = run(llm(errors=1, error="wrong_number"))
    assert (out.attempts, out.fallback) == (2, False)
    assert not out.verdicts[0].passed and "number 97" in out.verdicts[0].reasons[0]
    assert out.verdicts[1].passed


def test_retry_tells_the_narrator_why():
    client = llm(errors=1)
    run(client)
    narrator_prompts = [p for s, p in client.provider.calls if "ROLE: NARRATOR" in s]
    assert "was rejected. Fix: number 97" in narrator_prompts[1]


def test_three_failures_fall_back_to_the_template():
    out = run(llm(errors=3, error="invented_player"))
    assert (out.attempts, out.fallback) == (3, True)
    assert all(not v.passed for v in out.verdicts)
    assert out.overlay.text["en"] == prompts.fallback(analysis())
    assert verify(out.overlay.text["en"], analysis()).passed


def test_prediction_from_the_model_is_retried():
    out = run(llm(errors=1, error="prediction"))
    assert out.attempts == 2 and "no predictions" in out.verdicts[0].reasons[0]


def test_localizer_drops_a_translation_that_changes_numbers():
    def script(prompt, system):
        if "ROLE: LOCALIZER" in system:
            return "Riverside 0.99"  # a number the English line does not have
        return (
            FakeProvider(None).answer(prompt, system)
            if "ANALYST" in system
            else ("Riverside's control went from 0.71 to 0.81.")
        )

    out = run(llm(script=script))
    assert set(out.overlay.text) == {"en"}


def test_every_call_goes_through_the_budget():
    client = llm(errors=1)
    run(client)
    assert len(client.budget.ledger) == len(client.provider.calls) >= 4


# ---- Producer --------------------------------------------------------------------


def narrative(out_id, risk="low"):
    o = run(llm()).overlay
    return o.model_copy(update={"overlay_id": out_id, "risk_tier": risk})


def test_stat_card_airs_at_once():
    p = Producer()
    (aired,) = p.offer(
        stat_card(MOMENT, CONTEXT), moment_t=100, importance=0.9, now=100
    )
    assert aired.status == "aired" and aired.slot == "stat_card"


def test_stale_line_is_dropped():
    p = Producer()
    assert p.offer(narrative("a"), moment_t=100, importance=0.9, now=109) == []
    assert [o.status for o in p.expired] == ["expired"]


def test_one_narrative_per_45_s_most_important_first():
    p = Producer()
    (first,) = p.offer(narrative("a"), moment_t=100, importance=0.5, now=101)
    assert first.overlay_id == "a"
    # Within 45 s: both wait; the more important one airs when the gap allows.
    assert p.offer(narrative("b"), moment_t=140, importance=0.4, now=141) == []
    assert p.offer(narrative("c"), moment_t=140, importance=0.9, now=142) == []
    (next_,) = p.tick(now=146)
    assert next_.overlay_id == "c"
    # "b" (moment at 140) is stale by 149.
    p.tick(now=191.5)
    assert [o.overlay_id for o in p.expired] == ["b"]


def test_risky_line_waits_for_approval():
    p = Producer()
    assert (
        p.offer(narrative("r", risk="high"), moment_t=100, importance=0.9, now=101)
        == []
    )
    assert p.queue[0].overlay.status == "pending"
    (aired,) = p.approve("r", now=103)
    assert aired.status == "aired"


def test_deadlines_scale_with_replay_speed():
    # At 10x, 8 viewer seconds = 80 match seconds.
    p = Producer(speed=10)
    (aired,) = p.offer(narrative("a"), moment_t=100, importance=0.9, now=170)
    assert aired.overlay_id == "a"
