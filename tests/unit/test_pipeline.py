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
from agents.pipeline.verifier import lock, numbers, verify
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
    sent_off={R: 1},
    players={f"{R}-9": "Ada Brook", f"{HT}-11": "Juma Reed"},
)
# Analyst: these lines quote values (casual lines may not; see the casual tests).
TASK = NarrationTask(moment=MOMENT, context=CONTEXT, persona="analyst")


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


# The score is Riverside 0-1 Harbour in CONTEXT.
@pytest.mark.parametrize(
    "line",
    [
        "Riverside lead 0-1.",
        "Riverside grab control while leading Harbour 0-1.",
        "Harbour are trailing now.",
    ],
)
def test_saying_the_wrong_team_leads_is_rejected(line):
    verdict = verify(line, analysis())
    assert not verdict.passed and "wrong about the score" in verdict.reasons[0]


@pytest.mark.parametrize(
    "line", ["Harbour lead 0-1.", "Riverside trail 0-1.", "Harbour's lead holds."]
)
def test_saying_the_right_team_leads_passes(line):
    assert verify(line, analysis()).passed


def test_prompt_says_who_is_leading_and_who_the_red_card_helps():
    task = TASK.model_copy(
        update={"context": CONTEXT.model_copy(update={"sent_off": {R: 1}})}
    )
    block = prompts.values_block(task, values_of(task))
    assert '"Riverside": "trailing, a player down"' in block
    assert '"Harbour": "leading"' in block
    assert '"event": "Riverside had a player sent off"' in block
    assert '"good_for": "Harbour"' in block
    assert '"numbers_are_for": "Riverside"' in block


def test_copying_a_style_example_is_rejected():
    example = "Red card for Riverside! Their last man walks while trailing 0-1."
    copy = verify(example.replace("walks", "goes"), analysis(), [example])
    assert not copy.passed and "style example" in copy.reasons[0]
    assert verify("Riverside are a man down at 0-1.", analysis(), [example]).passed


def test_style_examples_are_labelled_do_not_copy():
    assert "DO NOT COPY" in prompts.narrator_system("casual")


# The Localizer sees numbers and names as tokens: "[T1]'s control went from
# [N1] to [N2]." for "Riverside's control went from 0.71 to 0.81."
LINE = "Riverside's control went from 0.71 to 0.81."
SW_TASK = TASK.model_copy(update={"languages": ["sw"]})


@pytest.mark.parametrize(
    "reply",
    [
        "[T1]'s control went from [N1] to [N2].",  # the English line itself
        "Udhibiti wa [T1] went from [N1] and [N2].",  # partly English
        "Udhibiti wa [T1] ulipanda kutoka [N1] hadi 0.9.",  # a token dropped
    ],
)
def test_localizer_retries_a_bad_translation_then_drops_it(reply):
    replies = []

    def script(prompt, system):
        if "ROLE: LOCALIZER" in system:
            replies.append(prompt)
            return reply
        if "ANALYST" in system:
            return FakeProvider(None).answer(prompt, system)
        return LINE

    out = run(llm(script=script), SW_TASK)
    assert set(out.overlay.text) == {"en"}
    assert len(replies) == 2 and "rejected" in replies[1]


def test_localizer_keeps_a_good_retry_with_the_numbers_put_back():
    def script(prompt, system):
        if "ROLE: LOCALIZER" in system:
            assert "0.71" not in prompt and "Riverside" not in prompt  # locked
            if "rejected" in prompt:
                return "Udhibiti wa [T1] ulipanda kutoka [N1] hadi [N2]."
            return "[T1]'s control went from [N1] to [N2]."
        if "ANALYST" in system:
            return FakeProvider(None).answer(prompt, system)
        return LINE

    out = run(llm(script=script), SW_TASK)
    assert (
        out.overlay.text["sw"]
        == "Udhibiti wa Riverside ulipanda kutoka 0.71 hadi 0.81."
    )


def test_four_languages_by_default():
    out = run(llm())
    assert set(out.overlay.text) == {"en", "fr", "es", "sw", "ar"}
    assert prompts.RIGHT_TO_LEFT == {"ar"}


@pytest.mark.parametrize(
    "line",
    [
        "Harbour seal it late on!",
        "That finish secures the 0-1 for Harbour.",
        "Game over for Riverside.",
        "Harbour have put it beyond doubt.",
        "Harbour clinch the win.",
        "Late knockout blow by Harbour!",
    ],
)
def test_soft_predictions_are_rejected(line):
    verdict = verify(line, analysis())
    assert not verdict.passed and "not over" in " ".join(verdict.reasons)


@pytest.mark.parametrize("line", ["Harbour make it 0-1.", "Harbour lead 0-1 now."])
def test_stating_the_score_is_not_a_prediction(line):
    assert verify(line, analysis()).passed


GOAL = MOMENT.model_copy(
    update={"kind": "goal", "team": HT, "metrics_before": {}, "metrics_after": {}}
)
COUNTER_FACTS = {
    "build_up": "counter-attack",
    "exploited_zone": "behind Riverside's left-back",
    "side": "left",
}


def goal_analysis():
    task = NarrationTask(
        moment=GOAL, context=CONTEXT, persona="casual", facts=COUNTER_FACTS
    )
    return analysis(task)


def test_counter_goal_line_must_name_the_counter_and_the_zone():
    bare = verify("Harbour score! 0-1.", goal_analysis())
    assert not bare.passed
    assert any("counter" in r for r in bare.reasons)
    assert any("behind Riverside's left-back" in r for r in bare.reasons)
    good = "Harbour break behind Riverside's left-back and score. 0-1!"
    assert verify(good, goal_analysis()).passed


def test_counter_goal_facts_reach_the_prompt_and_the_fallback():
    a = goal_analysis()
    assert '"exploited_zone": "behind Riverside\'s left-back"' in prompts.values_block(
        a.task, a.values
    )
    text = prompts.fallback(a)
    assert "counter behind Riverside's left-back" in text
    assert verify(text, a).passed


@pytest.mark.parametrize(
    "line",
    [
        "Red card! Riverside down to ten against Harbour trailing 0-1.",
        "Harbour behind Riverside's left-back again.",
        "Trailing 0-1, Riverside lose a man.",
    ],
)
def test_team_named_as_object_or_space_is_not_a_score_claim(line):
    assert verify(line, analysis()).passed


def test_giving_one_teams_numbers_to_the_other_is_rejected():
    # MOMENT is Riverside's: its control numbers are Riverside's.
    wrong = verify("The red card raises Harbour's control index to 0.81.", analysis())
    assert not wrong.passed and "Riverside's, not Harbour's" in wrong.reasons[0]
    assert verify("Riverside's control index rises to 0.81.", analysis()).passed


def casual_analysis(**update):
    return analysis(TASK.model_copy(update={"persona": "casual", **update}))


def test_casual_lines_show_no_index_numbers():
    verdict = verify("Riverside's control went from 0.71 to 0.81.", casual_analysis())
    assert not verdict.passed and "casual line" in verdict.reasons[0]
    assert verify("Riverside are pressed half as much now.", casual_analysis()).passed


def test_casual_prompt_gets_words_not_numbers():
    a = casual_analysis()
    block = prompts.values_block(a.task, a.values)
    assert '"How much Riverside are being pressed": "halved"' in block
    assert "0.52" not in block and "0.71" not in block


def test_analyst_prompt_gets_units():
    block = prompts.values_block(TASK, values_of(TASK))
    assert '"control_index": "index 0-1"' in block


def test_casual_fallback_uses_words():
    text = prompts.fallback(casual_analysis())
    assert not any(d for _, d, _ in numbers(text))
    assert verify(text, casual_analysis()).passed


@pytest.mark.parametrize(
    ("line", "ok"),
    [
        ("Pressure on Riverside's ball has halved.", True),  # 0.52 -> 0.245: 47%
        ("Riverside's control has doubled.", False),  # 0.712 -> 0.805
        ("Riverside's control is up by a third.", False),
    ],
)
def test_comparisons_must_match_a_real_change(line, ok):
    assert verify(line, analysis()).passed is ok


def goal_task(passes):
    return NarrationTask(
        moment=GOAL,
        context=CONTEXT,
        persona="analyst",
        facts=COUNTER_FACTS,
        counts={"passes_in_move": passes, "counter_goals": 2},
    )


@pytest.mark.parametrize(("passes", "ok"), [(1, True), (3, False)])
def test_one_pass_needs_a_one_pass_move(passes, ok):
    line = "One pass behind Riverside's left-back on the counter, and it's 0-1."
    assert verify(line, analysis(goal_task(passes))).passed is ok


@pytest.mark.parametrize(
    ("line", "ok"),
    [
        ("Harbour's second counter goal behind Riverside's left-back.", True),
        ("Harbour's third counter goal behind Riverside's left-back.", False),
        ("Twice Harbour break behind Riverside's left-back.", True),
        ("Ten men for Riverside as Harbour break behind the left-back.", True),
        ("Nine men for Riverside as Harbour break behind the left-back.", False),
        ("Harbour break behind Riverside's left-back once more.", True),
        ("Harbour break behind Riverside's left-back for 3 goals.", False),
    ],
)
def test_count_words_must_match_code_counts(line, ok):
    verdict = verify(line, analysis(goal_task(1)))
    assert verdict.passed is ok, verdict.reasons


def test_lock_types_the_tokens():
    masked, slots = lock("Harbour lead 0-1 with xG 0.61 at 34'.", analysis())
    assert masked == "[T1] lead [S1] with [X1] [N1] at [N2]'."
    assert slots["[S1]"] == "0-1" and slots["[T1]"] == "Harbour"


def test_a_decimal_before_goals_is_xg_not_a_count():
    from agents.pipeline.verifier import wrong_counts

    a = analysis(goal_task(1))
    assert wrong_counts("xG from 0.16 to 0.61 goals", a) == []
    assert wrong_counts("1.28 goals to 1.73 goals", a) == []
    assert wrong_counts("61 goals", a) != []
