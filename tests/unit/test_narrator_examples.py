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
    assert facts["sent_off"] == "Riverside's number 5"
    # Harbour won it in their own half and went 21 m forward 2 s later; two
    # Riverside defenders were goal-side, so not a last-man foul.
    assert facts["reason"] == "foul on a counter"
    assert task_for(demo, red, "analyst").counts == {"shirt_number": 5}


def test_demo_counter_goals_were_one_pass_moves(demo):
    goals = [m for m in demo.moments if m.kind == "goal"]
    assert [task_for(demo, m, "casual").counts for m in goals] == [
        {"passes_in_move": 1, "counter_goals": 1},
        {"passes_in_move": 1, "counter_goals": 2},
    ]
