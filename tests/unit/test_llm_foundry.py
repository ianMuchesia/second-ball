"""The Foundry provider (agents/llm/foundry.py) against a mock HTTP server:
the v1 request it sends, routing by agent, budget and kill switch, and every
way a call can fail. No network, no key."""

import json

import httpx
import pytest

from agents.llm import LLMClient, ProviderError, from_env
from agents.llm.base import CALL_ROLE
from agents.llm.foundry import FoundryProvider, v1_url
from agents.llm.prices import PRICES
from core.budget import Budget, BudgetExceeded

KEY = "test-key-not-real"
ENDPOINT = "https://sb-test.openai.azure.com"


def answer(text="A line.", model="gpt-4.1-mini-2025-04-14", prompt=120, completion=30):
    return {
        "model": model,
        "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": prompt, "completion_tokens": completion},
    }


def provider(handler, **kw):
    seen = []

    def record(request):
        seen.append(request)
        return handler(request)

    client = httpx.Client(
        transport=httpx.MockTransport(record), headers={"api-key": KEY}
    )
    kw.setdefault("roles", {"analyst": "gpt-5-mini"})
    p = FoundryProvider(ENDPOINT, KEY, "gpt-4.1-mini", client=client, **kw)
    return p, seen


def budget(usd_limit=1.0):
    return Budget(
        usd_limit=usd_limit,
        token_limit=1_000_000,
        run_id="test",
        prices=PRICES,
        kes_rate=130.0,
        kes_rate_date="2026-09-29",
    )


def test_v1_url_accepts_both_endpoint_forms():
    want = "https://sb-test.openai.azure.com/openai/v1/chat/completions"
    assert v1_url("https://sb-test.openai.azure.com") == want
    assert v1_url("https://sb-test.openai.azure.com/") == want
    assert v1_url("https://sb-test.openai.azure.com/openai/v1/") == want
    assert v1_url("https://sb.services.ai.azure.com").endswith(
        ".services.ai.azure.com/openai/v1/chat/completions"
    )


def test_the_v1_request_and_the_answer():
    p, seen = provider(lambda r: httpx.Response(200, json=answer()))
    r = p.generate("prompt", "system", 200)
    req = seen[0]
    body = json.loads(req.content)
    assert str(req.url) == v1_url(ENDPOINT)  # no api-version on the v1 API
    assert req.headers["api-key"] == KEY
    assert body["model"] == "gpt-4.1-mini"
    assert body["messages"] == [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "prompt"},
    ]
    assert body["max_completion_tokens"] == 200  # exactly what was prechecked
    assert "reasoning_effort" not in body  # gpt-4.1-mini does not reason
    assert (r.text, r.model, r.input_tokens, r.output_tokens) == (
        "A line.",
        "gpt-4.1-mini-2025-04-14",
        120,
        30,
    )


def test_the_analyst_goes_to_gpt5_mini_with_low_reasoning():
    p, seen = provider(lambda r: httpx.Response(200, json=answer(model="gpt-5-mini")))
    token = CALL_ROLE.set("analyst")
    try:
        assert p.model == "gpt-5-mini"
        p.generate("prompt", None, 300)
    finally:
        CALL_ROLE.reset(token)
    body = json.loads(seen[0].content)
    assert body["model"] == "gpt-5-mini" and body["reasoning_effort"] == "low"
    assert body["messages"] == [{"role": "user", "content": "prompt"}]
    assert p.model == "gpt-4.1-mini"  # other agents: the default deployment


def test_each_call_is_charged_at_its_deployments_price():
    p, _ = provider(
        lambda r: httpx.Response(200, json=answer(prompt=1_000, completion=500))
    )
    b = budget()
    llm = LLMClient(p, b)
    llm.complete("hi", max_output_tokens=500)
    token = CALL_ROLE.set("analyst")
    try:
        llm.complete("hi", max_output_tokens=500)
    finally:
        CALL_ROLE.reset(token)
    narrator, analyst = b.ledger[-2], b.ledger[-1]
    assert narrator["model"] == "gpt-4.1-mini"
    assert narrator["usd"] == pytest.approx(1_000 * 0.40 / 1e6 + 500 * 1.60 / 1e6)
    assert analyst["model"] == "gpt-5-mini"
    assert analyst["usd"] == pytest.approx(1_000 * 0.25 / 1e6 + 500 * 2.00 / 1e6)


def test_over_budget_no_request_is_sent_and_the_kill_switch_stays_on():
    p, seen = provider(lambda r: httpx.Response(200, json=answer()))
    llm = LLMClient(p, budget(usd_limit=0.00001))
    with pytest.raises(BudgetExceeded):
        llm.complete("hi", max_output_tokens=500)
    assert seen == [] and llm.killed
    with pytest.raises(BudgetExceeded, match="kill switch"):
        llm.complete("hi", max_output_tokens=5)
    assert seen == []


def test_a_deployment_with_no_price_is_blocked_before_any_request():
    p, seen = provider(lambda r: httpx.Response(200, json=answer()), roles={})
    p.default = "my-custom-deployment"
    with pytest.raises(BudgetExceeded):
        LLMClient(p, budget()).complete("hi", max_output_tokens=50)
    assert seen == []


@pytest.mark.parametrize(
    ("status", "retryable"),
    [(429, True), (500, True), (503, True), (400, False), (401, False), (404, False)],
)
def test_http_errors_say_whether_to_retry_and_never_show_the_key(status, retryable):
    body = {"error": {"code": "SomeCode", "message": "what went wrong"}}
    p, _ = provider(lambda r: httpx.Response(status, json=body))
    with pytest.raises(ProviderError) as e:
        p.generate("prompt", None, 50)
    assert e.value.retryable is retryable and e.value.status == status
    assert "what went wrong" in str(e.value) and KEY not in str(e.value)


def test_a_failed_call_is_not_charged():
    p, _ = provider(lambda r: httpx.Response(500, json={}))
    b = budget()
    with pytest.raises(ProviderError):
        LLMClient(p, b).complete("hi", max_output_tokens=50)
    assert not any(row["status"] == "allowed" for row in b.ledger)


def test_a_timeout_is_retryable_and_reported_as_408():
    def slow(request):
        raise httpx.ReadTimeout("slow", request=request)

    p, _ = provider(slow)
    with pytest.raises(ProviderError) as e:
        p.generate("prompt", None, 50)
    assert e.value.retryable and e.value.status == 408


def test_a_network_failure_is_retryable():
    def down(request):
        raise httpx.ConnectError("refused", request=request)

    p, _ = provider(down)
    with pytest.raises(ProviderError) as e:
        p.generate("prompt", None, 50)
    assert e.value.retryable


@pytest.mark.parametrize(
    "reply",
    [
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"choices": []}),
        httpx.Response(200, json={"choices": [{"message": {"content": "x"}}]}),
    ],
)
def test_a_malformed_answer_is_an_error_not_a_line(reply):
    p, _ = provider(lambda r: reply)
    with pytest.raises(ProviderError) as e:
        p.generate("prompt", None, 50)
    assert not e.value.retryable


def test_an_empty_answer_says_why():
    """A reasoning model can spend the whole allowance thinking."""
    empty = answer(text="", completion=300)
    empty["choices"][0]["finish_reason"] = "length"
    p, _ = provider(lambda r: httpx.Response(200, json=empty))
    with pytest.raises(ProviderError, match="finish_reason=length") as e:
        p.generate("prompt", None, 300)
    assert not e.value.retryable


def test_from_env_builds_foundry_with_both_deployments():
    env = {
        "MAX_RUN_USD": "0.5",
        "FOUNDRY_ENDPOINT": ENDPOINT,
        "FOUNDRY_API_KEY": KEY,
        "FOUNDRY_MODEL": "gpt-4.1-mini",
        "FOUNDRY_ANALYST_MODEL": "gpt-5-mini",
    }
    llm = from_env(env, provider="foundry")
    assert llm.provider.name == "foundry" and llm.budget.usd_limit == 0.5
    assert llm.provider.model == "gpt-4.1-mini"
    assert llm.provider.roles == {"analyst": "gpt-5-mini"}
    # Without a cap a real provider is refused (the kill switch).
    with pytest.raises(ValueError, match="MAX_RUN_USD"):
        from_env({k: v for k, v in env.items() if k != "MAX_RUN_USD"}, "foundry")


def test_in_the_pipeline_the_analyst_and_narrator_reach_their_deployments():
    """The agent's role travels with the call (CALL_ROLE, set per call by
    the pipeline) into the worker thread that makes the request."""
    import asyncio

    from agents.pipeline.workflow import narrate
    from tests.unit.test_resilience import TASK, fast_policy

    p, seen = provider(lambda r: httpx.Response(200, json=answer()))
    llm = LLMClient(p, budget())
    asyncio.run(narrate(llm, TASK, fast_policy(attempts=1)))
    models = [json.loads(r.content)["model"] for r in seen]
    assert models[0] == "gpt-5-mini"  # the Analyst goes first
    assert "gpt-4.1-mini" in models[1:]  # the Narrator after it
    assert [row["model"] for row in llm.budget.ledger] == models


def cut_off(text):
    reply = answer(text=text, prompt=200, completion=400)
    reply["choices"][0]["finish_reason"] = "length"
    return reply


def test_an_answer_cut_off_at_the_cap_is_an_error_not_a_line():
    p, _ = provider(lambda r: httpx.Response(200, json=cut_off("Harbour break and")))
    with pytest.raises(ProviderError, match="cut off.*finish_reason=length") as e:
        p.generate("prompt", None, 400)
    assert not e.value.retryable and e.value.usage == (200, 400)


@pytest.mark.parametrize("text", ["", "Harbour break and"])
def test_billed_tokens_of_a_cut_off_answer_are_charged(text):
    p, _ = provider(lambda r: httpx.Response(200, json=cut_off(text)))
    b = budget()
    with pytest.raises(ProviderError):
        LLMClient(p, b).complete("hi", max_output_tokens=400)
    row = b.ledger[-1]
    assert row["status"] == "allowed" and row["model"] == "gpt-4.1-mini"
    assert row["usd"] == pytest.approx(200 * 0.40 / 1e6 + 400 * 1.60 / 1e6)
    assert b.usd_spent == pytest.approx(row["usd"])


@pytest.mark.parametrize("text", ["", "Harbour break and"])
def test_in_the_pipeline_a_cut_off_answer_falls_back_to_a_template(text):
    import asyncio

    from agents.pipeline.workflow import narrate
    from tests.unit.test_resilience import TASK, fast_policy

    p, seen = provider(lambda r: httpx.Response(200, json=cut_off(text)))
    llm = LLMClient(p, budget())
    out = asyncio.run(narrate(llm, TASK, fast_policy(attempts=1)))
    assert seen and out.fallback  # no truncated text airs
    assert text == "" or text not in out.overlay.text
    assert len(llm.budget.ledger) == len(seen)  # every billed call charged


def test_the_analyst_may_use_1500_tokens_the_others_400():
    """gpt-5-mini thinks inside its cap: the Analyst gets room to answer;
    the budget prechecks the same cap the request carries."""
    import asyncio

    from agents.pipeline.workflow import narrate
    from tests.unit.test_resilience import TASK, fast_policy

    p, seen = provider(lambda r: httpx.Response(200, json=answer()))
    asyncio.run(narrate(LLMClient(p, budget()), TASK, fast_policy(attempts=1)))
    caps = {}
    for r in seen:
        body = json.loads(r.content)
        caps.setdefault(body["model"], set()).add(body["max_completion_tokens"])
    assert caps["gpt-5-mini"] == {1500}
    assert caps["gpt-4.1-mini"] == {400}
