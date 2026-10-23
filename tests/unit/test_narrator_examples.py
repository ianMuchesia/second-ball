"""Ian's six narrator lines are gold items: each must pass the Verifier against
the real demo moment it describes."""

import pytest
import yaml

from agents.mcp_server.data import MatchData
from agents.narrator import EXAMPLES, examples
from agents.pipeline.facts import facts_for, task_for
from agents.pipeline.models import Analysis
from agents.pipeline.verifier import verify
from agents.pipeline.workflow import values_of
from core.contracts import Insight
from engine.core import simulate_match
from engine.league import load_league
from engine.scenarios import load_scenario

ROWS = yaml.safe_load(EXAMPLES.read_text())["examples"]


@pytest.fixture(scope="module")
def demo():
    sc = load_scenario("demo_riverside_harbour")
    league = load_league()
    m = simulate_match(
        league[sc.home], league[sc.away], sc.seed, weather=sc.weather, scenario=sc
    )
    return MatchData(m.match, m.events)


def test_all_six_lines_are_written():
    assert len(examples("casual")) == len(examples("analyst")) == len(ROWS) == 3


@pytest.mark.parametrize("row", ROWS, ids=[r["moment"] for r in ROWS])
@pytest.mark.parametrize("persona", ["casual", "analyst"])
def test_line_passes_the_verifier_on_its_moment(demo, row, persona):
    (moment,) = [
        m
        for m in demo.moments
        if m.kind == row["kind"] and m.clock.minute == row["minute"]
    ]
    task = task_for(demo, moment, persona)
    analysis = Analysis(
        task=task,
        insight=Insight(
            claim="-",
            mechanism="-",
            evidence_event_ids=moment.evidence_event_ids,
            confidence=0.5,
        ),
        values=values_of(task),
    )
    verdict = verify(row[persona], analysis)
    assert verdict.passed, verdict.reasons
    assert len(row[persona].split()) <= 25


def test_both_demo_goals_are_counters_behind_the_left_back(demo):
    goals = [m for m in demo.moments if m.kind == "goal"]
    facts = [facts_for(demo, m) for m in goals]
    assert [f.get("exploited_zone") for f in facts] == [
        "behind Riverside's left-back"
    ] * 2
    assert "pattern" not in facts[0]
    assert facts[1]["pattern"].startswith("second counter goal")


def test_moments_other_than_goals_get_no_build_up(demo):
    assert all(
        "build_up" not in facts_for(demo, m) for m in demo.moments if m.kind != "goal"
    )


def test_red_card_facts_say_who_and_why_from_the_events(demo):
    (red,) = [m for m in demo.moments if m.kind == "red_card_impact"]
    facts = facts_for(demo, red)
    assert facts["sent_off"] == (
        "Riverside's left centre-back Ilya Stonebridge (number 5)"
    )
    # Harbour won it in their own half and went 21 m forward 2 s later, and
    # the high line was caught upfield: only the keeper behind.
    assert facts["reason"] == "last-man foul on a counter"
    assert task_for(demo, red, "analyst").counts == {}  # shirt: from the sheet


def test_same_foul_with_two_defenders_back_is_not_last_man(demo):
    """The night-before demo: two Riverside defenders goal-side. Code must not
    call it last man, and the Verifier must reject a line that does."""
    (red,) = [m for m in demo.moments if m.kind == "red_card_impact"]
    k = demo.by_id[red.evidence_event_ids[0]]
    foul = demo.events.items[k]
    mates = [
        p
        for p in foul.freeze_frame
        if p.team_id == foul.team_id and p.player_id != foul.player_id
    ]
    back = sorted(mates, key=lambda p: p.x)[1:3]  # two outfielders, not the keeper
    frame = [
        p.model_copy(update={"x": foul.start_x - 12.0}) if p in back else p
        for p in foul.freeze_frame
    ]
    items = list(demo.events.items)
    items[k] = foul.model_copy(update={"freeze_frame": frame})
    variant = MatchData(demo.match, items)
    facts = facts_for(variant, red)
    assert facts["reason"] == "foul on a counter"
    task = task_for(variant, red, "casual")
    a = Analysis(
        task=task,
        insight=Insight(
            claim="-",
            mechanism="-",
            evidence_event_ids=red.evidence_event_ids,
            confidence=0.5,
        ),
        values=values_of(task),
    )
    assert not verify("Red card! Riverside's last man walks.", a).passed


def test_demo_counter_goals_were_one_pass_moves(demo):
    goals = [m for m in demo.moments if m.kind == "goal"]
    assert [task_for(demo, m, "casual").counts for m in goals] == [
        {"passes_in_move": 1, "counter_goals": 1},
        {"passes_in_move": 1, "counter_goals": 2},
    ]


@pytest.mark.parametrize(
    ("line", "ok"),
    [
        ("Harbour break behind left-back Kofi Lindqvane on the counter. 0-2!", True),
        ("Harbour break behind right-back Lindqvane on the counter. 0-2!", False),
        (
            "Harbour break behind Lindqvane, Riverside's left-back, on the counter.",
            True,
        ),
        (
            "Dario Kestrelle, the target man, scores on the counter behind the left-back.",
            True,
        ),
        (
            "Dario Kestrelle, the false 9, scores on the counter behind the left-back.",
            False,
        ),
        ("Kestrelle, the striker, scores on the counter behind the left-back.", True),
        ("Number 9 Kestrelle scores on the counter behind the left-back.", True),
        ("Number 7 Kestrelle scores on the counter behind the left-back.", False),
        ("Number 23 scores on the counter behind the left-back.", False),
        ("Okafor scores on the counter behind the left-back.", False),
    ],
)
def test_names_positions_and_shirts_must_match_the_team_sheet(demo, line, ok):
    (goal,) = [m for m in demo.moments if m.kind == "goal" and m.clock.minute == 88]
    task = task_for(demo, goal, "casual")
    a = Analysis(
        task=task,
        insight=Insight(
            claim="-",
            mechanism="-",
            evidence_event_ids=goal.evidence_event_ids,
            confidence=0.5,
        ),
        values=values_of(task),
    )
    verdict = verify(line, a)
    assert verdict.passed is ok, verdict.reasons


def test_the_prompt_gets_the_team_sheet_and_the_sent_off_player(demo):
    from agents.pipeline import prompts

    (red,) = [m for m in demo.moments if m.kind == "red_card_impact"]
    task = task_for(demo, red, "analyst")
    block = prompts.values_block(task, values_of(task))
    assert "Kofi Lindqvane" in block and "left-back, overlapping full-back" in block
    assert "Ilya Stonebridge" not in task.context.players.values()  # sent off
    assert "Ilya Stonebridge" in block  # but named in the facts
