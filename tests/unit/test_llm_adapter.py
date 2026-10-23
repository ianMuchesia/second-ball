from types import SimpleNamespace

import pytest

from agents.llm import LLMClient, LLMResponse, from_env
from agents.llm.gemini import GeminiProvider
from agents.llm.prices import PRICES
from core.budget import Budget, BudgetExceeded

MODEL = "gemini-3.5-flash-lite"


class FakeProvider:
    name = "fake"
    model = MODEL

    def __init__(self, input_tokens=1_000, output_tokens=500):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.calls = 0

    def count_tokens(self, prompt, system):
        return self.input_tokens

    def generate(self, prompt, system, max_output_tokens):
        self.calls += 1
        return LLMResponse("ok", self.model, self.input_tokens, self.output_tokens)


def budget(usd_limit=1.0):
    return Budget(
        usd_limit=usd_limit,
        token_limit=1_000_000,
        run_id="test",
        prices=PRICES,
        kes_rate=130.0,
        kes_rate_date="2026-09-29",
    )


def test_call_is_charged_in_usd_and_kes():
    b = budget()
    LLMClient(FakeProvider(), b).complete("hi", max_output_tokens=500)
    row = b.ledger[-1]
    usd = 1_000 * 0.30 / 1e6 + 500 * 2.50 / 1e6
    assert row["status"] == "allowed"
    assert row["usd"] == pytest.approx(usd)
    assert row["kes"] == pytest.approx(usd * 130)


def test_kill_switch_blocks_before_provider_is_called():
    provider = FakeProvider()
    b = budget(usd_limit=0.0001)
    with pytest.raises(BudgetExceeded):
        LLMClient(provider, b).complete("hi", max_output_tokens=500)
    assert provider.calls == 0
    assert b.ledger[-1]["status"] == "blocked"


def test_unpriced_model_is_blocked():
    provider = FakeProvider()
    provider.model = "some-unpriced-model"
    with pytest.raises(BudgetExceeded):
        LLMClient(provider, budget()).complete("hi", max_output_tokens=500)
    assert provider.calls == 0


ENV = {"LLM_PROVIDER": "gemini", "GEMINI_API_KEY": "fake-key", "MAX_RUN_USD": "0.5"}


def test_from_env_builds_gemini_client_with_kill_switch():
    client = from_env(ENV)
    assert client.provider.name == "gemini"
    assert client.provider.model == MODEL
    assert client.budget.usd_limit == 0.5


def test_from_env_requires_max_run_usd():
    with pytest.raises(ValueError, match="MAX_RUN_USD"):
        from_env({k: v for k, v in ENV.items() if k != "MAX_RUN_USD"})


def test_from_env_rejects_unknown_provider():
    with pytest.raises(ValueError, match="LLM_PROVIDER"):
        from_env(ENV | {"LLM_PROVIDER": "openai"})


def test_foundry_is_a_stub():
    with pytest.raises(NotImplementedError):
        from_env(ENV | {"LLM_PROVIDER": "foundry"})


def test_gemini_requires_api_key():
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        from_env(ENV | {"GEMINI_API_KEY": ""})


def test_default_gemini_model_is_priced():
    assert from_env(ENV).provider.model in PRICES


class FakeGenaiModels:
    def __init__(self):
        self.config = None

    def count_tokens(self, model, contents):
        return SimpleNamespace(total_tokens=42)

    def generate_content(self, model, contents, config):
        self.config = config
        usage = SimpleNamespace(
            prompt_token_count=40, candidates_token_count=10, thoughts_token_count=5
        )
        return SimpleNamespace(text="hello", usage_metadata=usage)


def test_gemini_counts_thinking_tokens_as_output():
    models = FakeGenaiModels()
    provider = GeminiProvider(
        api_key=None, model=MODEL, client=SimpleNamespace(models=models)
    )
    assert provider.count_tokens("hi", "be brief") == 10  # bytes, counted locally
    response = provider.generate("hi", "be brief", max_output_tokens=64)
    assert (response.text, response.input_tokens, response.output_tokens) == (
        "hello",
        40,
        15,
    )
    assert models.config.max_output_tokens == 64


def test_gemini_paces_requests_under_the_per_minute_cap():
    now, slept = [0.0], []

    def sleep(s):
        slept.append(s)
        now[0] += s

    provider = GeminiProvider(
        api_key=None,
        model=MODEL,
        client=SimpleNamespace(models=FakeGenaiModels()),
        rpm=30,
        clock=lambda: now[0],
        sleep=sleep,
    )
    provider.generate("hi", None, max_output_tokens=8)
    provider.generate("hi", None, max_output_tokens=8)  # 2 s gap at 30 a minute
    now[0] += 5.0
    provider.generate("hi", None, max_output_tokens=8)  # already far enough apart
    assert slept == [2.0]


def test_gemini_client_retries_rate_limit_errors():
    from agents.llm.gemini import RETRY

    assert 429 in RETRY.http_status_codes and RETRY.attempts > 1


def test_concurrent_calls_cannot_interleave_precheck_and_charge():
    import threading

    from agents.llm.fake import FakeProvider
    from core.budget import Budget

    budget = Budget(
        usd_limit=1.0,
        token_limit=10_000_000,
        run_id="t",
        prices=PRICES,
        kes_rate=130,
        kes_rate_date="2026-09-29",
    )
    client = LLMClient(
        FakeProvider(failures={"other": ["timeout"] * 4}, slow_s=0.05), budget
    )
    errors = []

    def call():
        try:
            client.complete("hi", max_output_tokens=8)
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=call) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == [] and len(budget.ledger) == 8


def test_gemini_request_gets_its_own_timeout():
    models = FakeGenaiModels()
    provider = GeminiProvider(
        api_key=None, model=MODEL, client=SimpleNamespace(models=models)
    )
    provider.generate("hi", None, max_output_tokens=8, timeout_s=12)
    assert models.config.http_options.timeout == 12_000
