"""The repeat-run report, on the fake model (free, no network)."""

import asyncio

from agents.llm import LLMClient
from agents.llm.fake import FakeProvider
from agents.llm.prices import PRICES
from agents.mcp_server.data import MatchData
from core.budget import Budget
from engine.core import simulate_match
from engine.league import load_league
from engine.scenarios import load_scenario
from evals.narration.report import label, render, run
from evals.sections import keep_sections, write_section


def demo():
    sc = load_scenario("demo_riverside_harbour")
    league = load_league()
    m = simulate_match(
        league[sc.home], league[sc.away], sc.seed, weather=sc.weather, scenario=sc
    )
    return MatchData(m.match, m.events)


def fake(**kw):
    budget = Budget(
        usd_limit=0.10,
        token_limit=1_000_000,
        run_id="t",
        prices=PRICES,
        kes_rate=130,
        kes_rate_date="2026-09-29",
    )
    return LLMClient(FakeProvider(**kw), budget)


def test_report_counts_first_pass_retries_and_translations():
    llm = fake(errors=1)  # the very first Narrator answer is wrong
    tallies, kept = asyncio.run(run(demo(), llm, runs=2, translation_runs=1))
    lines = sum(t.runs for t in tallies.values())
    assert lines == 2 * 3 * 2  # runs x moments x personas
    assert sum(t.retried for t in tallies.values()) == 1
    assert sum(t.first + t.retried + t.fallback for t in tallies.values()) == lines
    assert all(n == 6 for _, n in kept.values())  # 1 run x 6 lines per language
    text = render(tallies, kept, llm, 2, 1, 60.0)
    assert "fake-model" in text and "number not in the evidence: 1" in text


def test_reasons_get_short_labels():
    assert label("number 97 is not in the values or the match context") == (
        "number not in the evidence"
    )
    assert label("the control numbers are Riverside's, not Harbour's") == (
        "numbers given to the wrong team"
    )


def test_reports_share_eval_md_by_sections(tmp_path):
    path = tmp_path / "EVAL.md"
    write_section(path, "narration", "N1")
    path.write_text(keep_sections("# Moments v2", path, ["narration"]))
    write_section(path, "narration", "N2")
    text = path.read_text()
    assert text.startswith("# Moments v2") and "N2" in text and "N1" not in text
