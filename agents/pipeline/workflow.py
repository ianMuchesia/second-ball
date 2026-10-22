"""The narration workflow (Microsoft Agent Framework).

    Analyst -> Narrator -> Verifier -+-> Localizer -> Narration (Overlay, pending)
                  ^                  |
                  +---- Retry -------+   (at most 2 retries, then the fallback)

Analyst, Narrator and Localizer are agents (a model behind our adapter);
the Verifier is plain code. Numbers come from code (Analysis.values); the
fallback sentence is built from those values only.

Every model and MCP call goes through agents.pipeline.resilience (time budget,
retry with backoff, then a code fallback; the budget kill switch), and every
step is a span in the moment's trace (agents.telemetry). Whatever fails,
`narrate` returns a Narration with an English line: never an empty overlay.
"""

import json
import logging
from datetime import UTC, datetime

from agent_framework import Agent, Executor, WorkflowBuilder, WorkflowContext, handler

from agents.llm import LLMClient
from agents.narrator import examples
from agents.pipeline import prompts
from agents.pipeline.client import AdapterChatClient
from agents.pipeline.models import (
    Analysis,
    Approved,
    Draft,
    Narration,
    NarrationTask,
    Retry,
    Verdict,
)
from agents.pipeline.resilience import Policy, ask, call_tool
from agents.pipeline.verifier import lock, unlock, untranslated, verify, wrong_numbers
from agents.telemetry import step
from core.contracts import Insight, Overlay
from core.contracts.overlay import OverlayTime

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 3  # the first line + 2 retries
LOCALIZER_ATTEMPTS = 2  # a translation + 1 retry
DURATION_MS = 6000
SEQUENCE_BEFORE = 6  # events before the moment's last evidence event, for the Analyst
UNAVAILABLE = "the model gave no answer (timeout, error or kill switch)"


def values_of(task: NarrationTask) -> dict[str, float]:
    """Code-made numbers the line may quote: the moment's before/after metrics."""
    m = task.moment
    out = {f"{k}_before": v.value for k, v in m.metrics_before.items()}
    for k, v in m.metrics_after.items():
        out[f"{k}_after" if k in m.metrics_before else k] = v.value
    return out


def parse_insight(text: str | None, task: NarrationTask) -> Insight:
    """The Analyst's JSON; if it is missing or not usable, a plain claim from code."""
    try:
        raw = (text or "").strip().removeprefix("```json").removesuffix("```")
        data = json.loads(raw)
        claim, mechanism = str(data["claim"]).strip(), str(data["mechanism"]).strip()
        confidence = min(1.0, max(0.0, float(data.get("confidence", 0.5))))
    except (ValueError, KeyError, TypeError):
        claim = f"{task.moment.kind.replace('_', ' ')}"
        mechanism, confidence = "See the numbers before and after.", 0.3
    # A claim code knows (who was sent off and why) is code's, not the model's.
    claim = task.facts.get("claim", claim)
    return Insight(
        claim=claim or "-",
        mechanism=mechanism or "-",
        evidence_event_ids=task.moment.evidence_event_ids,
        confidence=confidence,
    )


def sequence_lines(seq: dict | None, task: NarrationTask) -> list[str]:
    """The MCP sequence as short lines (no coordinates: nothing to misquote)."""
    if not seq:
        return []
    names = task.context.team_names
    return [
        f"{names.get(e['team_id'], e['team_id'])} {e['type']} ({e['outcome']})"
        for e in seq.get("events", [])
    ]


class AnalystExecutor(Executor):
    def __init__(self, llm: LLMClient, policy: Policy, tools=None):
        super().__init__(id="analyst")
        self.llm, self.policy, self.tools = llm, policy, tools
        self.agent = Agent(
            client=AdapterChatClient(llm), instructions=prompts.ANALYST, name="analyst"
        )

    @handler
    async def analyse(
        self, task: NarrationTask, ctx: WorkflowContext[Analysis]
    ) -> None:
        with step("analyst") as span:
            values = values_of(task)
            seq = await call_tool(
                self.tools,
                "get_sequence",
                {
                    "event_id": task.moment.evidence_event_ids[-1],
                    "before": SEQUENCE_BEFORE,
                    "after": 0,
                },
                self.policy,
            )
            prompt = prompts.analyst_prompt(task, values, sequence_lines(seq, task))
            reply = await ask(self.llm, self.agent, prompt, "analyst", self.policy)
            insight = parse_insight(reply, task)
            span.set_attributes(
                {
                    "code_insight": reply is None,
                    "mcp_sequence": seq is not None,
                    "confidence": insight.confidence,
                }
            )
        await ctx.send_message(Analysis(task=task, insight=insight, values=values))


class NarratorExecutor(Executor):
    def __init__(self, llm: LLMClient, policy: Policy):
        super().__init__(id="narrator")
        self.llm, self.policy = llm, policy
        self.agents: dict[str, Agent] = {}

    def agent(self, persona: str) -> Agent:
        if persona not in self.agents:
            self.agents[persona] = Agent(
                client=AdapterChatClient(self.llm),
                instructions=prompts.narrator_system(persona),
                name=f"narrator_{persona}",
            )
        return self.agents[persona]

    async def write(
        self, analysis: Analysis, attempt: int, reasons, history, ctx
    ) -> None:
        with step("narrator", attempt=attempt) as span:
            reply = await ask(
                self.llm,
                self.agent(analysis.task.persona),
                prompts.narrator_prompt(analysis, reasons),
                "narrator",
                self.policy,
            )
            span.set_attribute("answered", reply is not None)
        await ctx.send_message(
            Draft(
                analysis=analysis,
                text=(reply or "").strip(),
                attempt=attempt,
                history=history,
                unavailable=reply is None,
            )
        )

    @handler
    async def first(self, analysis: Analysis, ctx: WorkflowContext[Draft]) -> None:
        await self.write(analysis, 1, [], [], ctx)

    @handler
    async def again(self, retry: Retry, ctx: WorkflowContext[Draft]) -> None:
        await self.write(
            retry.analysis, retry.attempt, retry.reasons, retry.history, ctx
        )


def fallback_approved(analysis: Analysis, attempts: int, history) -> Approved:
    text = prompts.fallback(analysis)
    return Approved(
        analysis=analysis,
        text=text,
        verdict=verify(text, analysis),
        fallback=True,
        attempts=attempts,
        history=history,
    )


class VerifierExecutor(Executor):
    """Plain code: pass -> Localizer; fail -> Retry (max 2); then fallback.
    No answer from the model (after resilience's own retry) -> fallback now."""

    def __init__(self):
        super().__init__(id="verifier")

    @handler
    async def check(self, draft: Draft, ctx: WorkflowContext[Retry | Approved]) -> None:
        with step("verifier", attempt=draft.attempt) as span:
            if draft.unavailable:
                verdict = Verdict(passed=False, reasons=[UNAVAILABLE])
            else:
                verdict = verify(
                    draft.text, draft.analysis, examples(draft.analysis.task.persona)
                ).model_copy(update={"text": draft.text})
            span.set_attributes(
                {
                    "passed": verdict.passed,
                    "reasons": verdict.reasons,
                    "risk_tier": verdict.risk_tier,
                }
            )
        history = [*draft.history, verdict]
        if verdict.passed:
            await ctx.send_message(
                Approved(
                    analysis=draft.analysis,
                    text=draft.text,
                    verdict=verdict,
                    fallback=False,
                    attempts=draft.attempt,
                    history=history,
                )
            )
        elif draft.attempt < MAX_ATTEMPTS and not draft.unavailable:
            await ctx.send_message(
                Retry(
                    analysis=draft.analysis,
                    attempt=draft.attempt + 1,
                    reasons=verdict.reasons,
                    history=history,
                )
            )
        else:
            await ctx.send_message(
                fallback_approved(draft.analysis, draft.attempt, history)
            )


async def localize(
    llm: LLMClient, policy: Policy, text: str, analysis: Analysis, languages
) -> dict[str, str]:
    """{"en": text, lang: translation, ...}. Numbers and names are locked as
    typed tokens; each translation is checked in code (tokens intact, numbers
    allowed, not still English); one retry with the reason, then that language
    is dropped (English always airs)."""
    out = {"en": text}
    masked, slots = lock(text, analysis)
    for lang in languages:
        with step(f"localizer.{lang}") as span:
            agent = Agent(
                client=AdapterChatClient(llm),
                instructions=prompts.LOCALIZER.format(
                    language=prompts.LANGUAGE.get(lang, lang)
                ),
                name=f"localizer_{lang}",
            )
            request = f"TEXT: {masked}"
            problem = None
            for _ in range(LOCALIZER_ATTEMPTS):
                reply = await ask(llm, agent, request, "localizer", policy)
                if reply is None:
                    problem = UNAVAILABLE
                    break
                translation, problem = unlock(reply.strip(), slots)
                if translation is not None:
                    # The Verifier again, on the translation.
                    problem = untranslated(translation, text) or next(
                        iter(wrong_numbers(translation, analysis)), None
                    )
                if problem is None:
                    out[lang] = translation
                    break
                request = f"Your last reply was rejected: {problem}.\nTEXT: {masked}"
            span.set_attributes({"kept": lang in out, "problem": problem})
    return out


class LocalizerExecutor(Executor):
    def __init__(self, llm: LLMClient, policy: Policy):
        super().__init__(id="localizer")
        self.llm, self.policy = llm, policy

    @handler
    async def localize(
        self, approved: Approved, ctx: WorkflowContext[None, Narration]
    ) -> None:
        text = await localize(
            self.llm,
            self.policy,
            approved.text,
            approved.analysis,
            approved.analysis.task.languages,
        )
        await ctx.yield_output(
            Narration(
                overlay=overlay(approved, text),
                fallback=approved.fallback,
                attempts=approved.attempts,
                verdicts=approved.history,
            )
        )


def overlay(approved: Approved, text: dict[str, str]) -> Overlay:
    task = approved.analysis.task
    m = task.moment
    risk = approved.verdict.risk_tier
    return Overlay(
        overlay_id=f"{m.moment_id}-{task.persona}",
        match_id=task.context.match_id,
        kind=m.kind,
        slot="narrative",
        t_in=OverlayTime(match=m.clock, wall=datetime.now(UTC)),
        duration_ms=DURATION_MS,
        priority=round(m.importance * 100),
        risk_tier=risk,
        text=text,
        values=approved.analysis.values,
        evidence_event_ids=m.evidence_event_ids,
        status="pending",
    )


def build(llm: LLMClient, policy: Policy | None = None, tools=None):
    policy = policy or Policy()
    analyst = AnalystExecutor(llm, policy, tools)
    narrator = NarratorExecutor(llm, policy)
    verifier = VerifierExecutor()
    localizer = LocalizerExecutor(llm, policy)
    return (
        WorkflowBuilder(start_executor=analyst, max_iterations=20)
        .add_edge(analyst, narrator)
        .add_edge(narrator, verifier)
        .add_edge(verifier, narrator, condition=lambda msg: isinstance(msg, Retry))
        .add_edge(verifier, localizer, condition=lambda msg: isinstance(msg, Approved))
        .build()
    )


def emergency(task: NarrationTask, error: Exception) -> Narration:
    """The workflow itself failed: the code template, English only."""
    values = values_of(task)
    analysis = Analysis(task=task, insight=parse_insight(None, task), values=values)
    verdict = Verdict(
        passed=False, reasons=[f"workflow failed: {type(error).__name__}"]
    )
    approved = fallback_approved(analysis, 0, [verdict])
    return Narration(
        overlay=overlay(approved, {"en": approved.text}),
        fallback=True,
        attempts=0,
        verdicts=[verdict],
    )


async def narrate(
    llm: LLMClient, task: NarrationTask, policy: Policy | None = None, tools=None
) -> Narration:
    """Run the workflow for one moment and persona (one `narrate` span)."""
    m = task.moment
    with step(
        "narrate",
        moment_id=m.moment_id,
        kind=m.kind,
        minute=m.clock.minute,
        persona=task.persona,
        importance=m.importance,
    ) as span:
        n = len(llm.budget.ledger)
        try:
            result = await build(llm, policy, tools).run(task)
            (out,) = result.get_outputs()
        except Exception as e:  # never an empty overlay
            log.exception("narration workflow failed for %s", m.moment_id)
            span.set_attribute("error", repr(e)[:200])
            out = emergency(task, e)
        rows = llm.budget.ledger[n:]
        span.set_attributes(
            {
                "fallback": out.fallback,
                "attempts": out.attempts,
                "languages": sorted(out.overlay.text),
                "llm.calls": len(rows),
                "llm.usd": sum(r.get("usd") or 0.0 for r in rows),
            }
        )
    return out


__all__ = ["MAX_ATTEMPTS", "Policy", "Verdict", "build", "narrate", "values_of"]
