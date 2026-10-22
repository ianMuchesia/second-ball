import logging
import os
import uuid

from dotenv import load_dotenv

from agents.llm.fake import FakeProvider
from agents.llm.foundry import FoundryProvider
from agents.llm.gemini import GeminiProvider
from agents.llm.prices import PRICES
from core.budget import Budget

log = logging.getLogger(__name__)

DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"
# Requests a minute we allow ourselves; set GEMINI_RPM to your project's AI
# Studio limit (a little under it). Low default: safe on the free tier.
DEFAULT_GEMINI_RPM = 10
DEFAULT_MAX_RUN_TOKENS = 500_000
DEFAULT_KES_RATE = 130.0
DEFAULT_KES_RATE_DATE = "2026-09-29"


class LLMClient:
    """The only way agents call a model. Every call goes through core/budget.py."""

    def __init__(self, provider, budget):
        self.provider = provider
        self.budget = budget

    def complete(self, prompt, *, max_output_tokens, system=None):
        model = self.provider.model
        input_tokens = self.provider.count_tokens(prompt, system)
        # Raises BudgetExceeded (and logs a blocked row) before any paid call.
        self.budget.precheck(model, input_tokens, max_output_tokens)
        response = self.provider.generate(prompt, system, max_output_tokens)
        self.budget.charge(model, response.input_tokens, response.output_tokens)
        log.info("llm call %s", self.budget.ledger[-1])
        return response


def from_env(env=None):
    """Build the client from LLM_PROVIDER, MAX_RUN_USD etc. Reads .env when env is None."""
    if env is None:
        load_dotenv()
        env = os.environ

    provider_name = env.get("LLM_PROVIDER", "gemini")
    if provider_name == "gemini":
        provider = GeminiProvider(
            api_key=env.get("GEMINI_API_KEY"),
            model=env.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL),
            rpm=float(env.get("GEMINI_RPM", DEFAULT_GEMINI_RPM)),
        )
    elif provider_name == "foundry":
        provider = FoundryProvider(
            endpoint=env.get("FOUNDRY_ENDPOINT"),
            api_key=env.get("FOUNDRY_API_KEY"),
            model=env.get("FOUNDRY_MODEL"),
        )
    elif provider_name == "fake":
        provider = FakeProvider()  # tests and offline runs: free, no network
    else:
        raise ValueError(
            f"unknown LLM_PROVIDER {provider_name!r}; use 'gemini', 'foundry' or 'fake'"
        )

    if not env.get("MAX_RUN_USD"):
        raise ValueError("MAX_RUN_USD must be set (the kill switch)")

    budget = Budget(
        usd_limit=float(env["MAX_RUN_USD"]),
        token_limit=int(env.get("MAX_RUN_TOKENS", DEFAULT_MAX_RUN_TOKENS)),
        run_id=env.get("RUN_ID") or str(uuid.uuid4()),
        prices=PRICES,
        kes_rate=float(env.get("KES_RATE", DEFAULT_KES_RATE)),
        kes_rate_date=env.get("KES_RATE_DATE", DEFAULT_KES_RATE_DATE),
    )
    return LLMClient(provider, budget)
