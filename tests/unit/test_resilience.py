"""Failure recovery: every path ends in an English line, never an empty
overlay. Uses the fake model's failure modes (no network, no cost)."""

import asyncio

import pytest

from agents.llm import LLMClient
from agents.llm.fake import FakeProvider
from agents.llm.prices import PRICES
from agents.mcp_server import build as build_mcp
from agents.pipeline import prompts
from agents.pipeline.resilience import Policy, mcp_tools
from agents.pipeline.workflow import narrate
from agents.telemetry import RECORDER, setup
from core.budget import Budget
from tests.unit.test_pipeline import TASK, analysis

setup()


def fast_policy(**kw):
    async def no_sleep(_):
        return None

    return Policy(
        timeout_s={"analyst": 0.2, "narrator": 0.2, "localizer": 0.2, "recap": 0.2},
        sleep=no_sleep,
        **kw,
    )


def client(usd_limit=0.10, **fake):
    budget = Budget(
        usd_limit=usd_limit,
        token_limit=1_000_000,
        run_id="t",
        prices=PRICES,
        kes_rate=130,
        kes_rate_date="2026-09-29",
    )
    return LLMClient(FakeProvider(**fake), budget)


def run(llm, task=TASK, **kw):
    return asyncio.run(narrate(llm, task, fast_policy(), **kw))


def spans(name):
    return [s for s in RECORDER.spans if s.name == name]


def test_a_timeout_is_retried_once_then_the_line_comes():
    RECORDER.clear()
    out = run(client(failures={"narrator": ["timeout"]}, slow_s=0.5))
    assert not out.fallback and out.overlay.text["en"]
    outcomes = [s.attributes["outcome"] for s in spans("llm.narrator")]
    assert outcomes[:2] == ["timeout", "ok"]


@pytest.mark.parametrize("mode", ["rate_limit", "server_error"])
def test_a_429_or_503_is_retried_after_a_pause(mode):
    paused = []

    async def sleep(s):
        paused.append(s)

    policy = Policy(sleep=sleep)
    out = asyncio.run(narrate(client(failures={"narrator": [mode]}), TASK, policy))
    assert not out.fallback and paused == [policy.backoff_s]


def test_the_model_down_means_the_template_at_once():
    out = run(client(failures={"narrator": ["rate_limit", "rate_limit"]}))
    assert out.fallback and out.attempts == 1
    assert out.overlay.text["en"] == prompts.fallback(analysis())


def test_a_bad_request_is_not_retried():
    llm = client(failures={"narrator": ["bad_request"]})
    out = run(llm)
    assert out.fallback
    narrator_calls = [s for s, _ in llm.provider.calls if "NARRATOR" in (s or "")]
    assert narrator_calls == []  # failed before answering, and no retry


def test_malformed_analyst_json_becomes_a_code_insight():
    RECORDER.clear()
    out = run(client(failures={"analyst": ["malformed"]}))
    assert not out.fallback
    (analyst,) = spans("analyst")
    assert analyst.attributes["confidence"] == 0.3


def test_an_empty_line_is_sent_back_like_any_bad_line():
    llm = client(
        script=lambda p, s: "" if "NARRATOR" in s else FakeProvider().answer(p, s)
    )
    out = run(llm)
    assert out.fallback and out.verdicts[0].reasons == ["the line is empty"]


def test_a_failed_translation_drops_only_that_language():
    llm = client(failures={"localizer": ["bad_request"]})
    out = run(llm, TASK.model_copy(update={"languages": ["fr", "sw"]}))
    assert set(out.overlay.text) == {"en", "sw"}


def test_the_budget_kill_switch_stops_model_calls_and_uses_templates():
    llm = client(usd_limit=0.0)  # nothing is affordable
    out = run(llm)
    assert out.fallback and llm.killed
    assert llm.provider.calls == []  # no model call was made
    again = run(llm)  # later moments: templates straight away
    assert again.fallback and llm.provider.calls == []


def test_mcp_tool_error_is_retried_then_the_analyst_goes_on_without_it():
    RECORDER.clear()
    calls = []

    async def broken(name, args):
        calls.append(name)
        raise RuntimeError("tool down")

    out = run(client(), tools=broken)
    assert not out.fallback and calls == ["get_sequence", "get_sequence"]
    (analyst,) = spans("analyst")
    assert analyst.attributes["mcp_sequence"] is False


def test_the_analyst_reads_the_sequence_through_the_mcp_server():
    from tests.unit.test_narration_report import demo

    data = demo()
    tools = mcp_tools(build_mcp(data))
    (red,) = [m for m in data.moments if m.kind == "red_card_impact"]
    from agents.pipeline.facts import task_for

    llm = client()
    asyncio.run(narrate(llm, task_for(data, red, "analyst", []), fast_policy(), tools))
    analyst_prompt = next(p for s, p in llm.provider.calls if "ANALYST" in (s or ""))
    assert "SEQUENCE" in analyst_prompt and "Harbour interception (success)" in (
        analyst_prompt
    )


def test_a_crashing_workflow_still_gives_a_line(monkeypatch):
    import agents.pipeline.workflow as wf

    def boom(*a, **k):
        raise RuntimeError("bug")

    monkeypatch.setattr(wf, "build", boom)
    out = run(client())
    assert out.fallback and out.overlay.text["en"]
    assert "workflow failed" in out.verdicts[0].reasons[0]


def test_one_trace_per_moment_with_a_span_per_step():
    RECORDER.clear()
    run(client(errors=1), TASK.model_copy(update={"languages": ["sw"]}))
    (root,) = spans("narrate")
    trace_id = root.context.trace_id
    names = [s.name for s in RECORDER.spans if s.context.trace_id == trace_id]
    for name in ["analyst", "llm.analyst", "narrator", "verifier", "localizer.sw"]:
        assert name in names
    verdicts = spans("verifier")
    assert verdicts[0].attributes["passed"] is False
    assert "not in the values" in verdicts[0].attributes["reasons"][0]
    assert root.attributes["llm.calls"] >= 4
