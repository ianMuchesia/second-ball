"""Ian's six narrator lines are gold items: each must pass the Verifier against
the real demo moment it describes."""

import pytest
import yaml

from agents.mcp_server.data import MatchData
from agents.narrator import EXAMPLES, examples
from agents.pipeline.facts import context_at, facts_for
from agents.pipeline.models import Analysis, NarrationTask
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
    task = NarrationTask(
        moment=moment,
        context=context_at(demo, moment),
        persona=persona,
        facts=facts_for(demo, moment),
    )
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
    assert all(facts_for(demo, m) == {} for m in demo.moments if m.kind != "goal")
