"""Failure recovery for every model and tool call in the pipeline.

Each agent call has a time budget (Policy.timeout_s, per role). A timeout, a
rate limit (429) or a server/network error gets one retry after a pause
(exponential backoff); a bad request is not retried. If there is still no
answer, `ask` returns None and the caller falls back to code: a code-made
Insight, the code template line, or no translation (English always airs).
BudgetExceeded trips the kill switch (LLMClient.killed): no model calls for
the rest of the run, templates only. Never an empty overlay.

The free-tier request limit is respected below this layer: GeminiProvider
paces requests to GEMINI_RPM and its SDK retries 429s first.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from agents.llm import LLMClient, ProviderError
from agents.llm.client import CALL_TIMEOUT
from agents.telemetry import step
from core.budget import BudgetExceeded

log = logging.getLogger(__name__)

# Seconds per model request, by role. The limit is set on the HTTP request
# itself (so a slow call really stops; a call left running in a thread would
# hold the client), not on the pacing wait before it. Generous: on the free
# tier a request can take 15 s when Google answers 429 and the SDK waits.
TIMEOUT_S = {"analyst": 20.0, "narrator": 20.0, "localizer": 20.0, "recap": 25.0}
BACKSTOP_S = 90.0  # asyncio guard on top, for a provider that ignores its timeout


@dataclass
class Policy:
    timeout_s: dict[str, float] = field(default_factory=lambda: dict(TIMEOUT_S))
    attempts: int = 2  # the call + 1 retry
    backoff_s: float = 2.0  # pause before retry n: backoff_s * 2**(n-1)
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep


def cost_since(llm: LLMClient, n: int) -> dict:
    rows = llm.budget.ledger[n:]
    return {
        "llm.model": llm.provider.model,
        "llm.calls": len(rows),
        "llm.input_tokens": sum(r.get("input_tokens") or 0 for r in rows),
        "llm.output_tokens": sum(r.get("output_tokens") or 0 for r in rows),
        "llm.usd": sum(r.get("usd") or 0.0 for r in rows),
    }


async def ask(llm: LLMClient, agent, prompt: str, role: str, policy: Policy):
    """The agent's reply text, or None (the caller uses its code fallback)."""
    for attempt in range(1, policy.attempts + 1):
        if llm.killed:
            with step(f"llm.{role}", attempt=attempt, outcome="kill_switch"):
                return None
        n = len(llm.budget.ledger)
        with step(f"llm.{role}", attempt=attempt) as span:
            token = CALL_TIMEOUT.set(policy.timeout_s[role])
            try:
                reply = await asyncio.wait_for(
                    agent.run(prompt), policy.timeout_s[role] + BACKSTOP_S
                )
                span.set_attributes({**cost_since(llm, n), "outcome": "ok"})
                return reply.text
            except BudgetExceeded as e:
                llm.killed = True
                span.set_attributes({"outcome": "kill_switch", "error": str(e)})
                log.warning("budget kill switch: %s", e)
                return None
            except TimeoutError:
                span.set_attributes({"outcome": "timeout"})
            except ProviderError as e:
                span.set_attributes(
                    {
                        "outcome": "timeout" if e.status == 408 else "error",
                        "error": str(e),
                        "retryable": e.retryable,
                    }
                )
                if not e.retryable:
                    return None
            finally:
                CALL_TIMEOUT.reset(token)
        if attempt < policy.attempts:
            await policy.sleep(policy.backoff_s * 2 ** (attempt - 1))
    return None


async def call_tool(tools, name: str, args: dict, policy: Policy):
    """An MCP tool call with one retry; None if it still fails."""
    if tools is None:
        return None
    for attempt in range(1, policy.attempts + 1):
        with step(f"mcp.{name}", attempt=attempt) as span:
            try:
                out = await tools(name, args)
                span.set_attribute("outcome", "ok")
                return out
            except Exception as e:  # noqa: BLE001 - any tool failure: retry, then go on without
                span.set_attributes({"outcome": "error", "error": repr(e)[:200]})
        if attempt < policy.attempts:
            await policy.sleep(policy.backoff_s * 2 ** (attempt - 1))
    return None


def mcp_tools(server):
    """`tools(name, args)` over an in-process MCP server (agents.mcp_server)."""

    async def tools(name: str, args: dict):
        result = await server.call_tool(name, args)
        if result.is_error:
            raise RuntimeError(f"MCP tool {name} returned an error")
        return result.structured_content

    return tools
