"""The narration workflow (Microsoft Agent Framework).

    Analyst -> Narrator -> Verifier -+-> Localizer -> Narration (Overlay, pending)
                  ^                  |
                  +---- Retry -------+   (at most 2 retries, then the fallback)

Analyst, Narrator and Localizer are agents (a model behind our adapter);
the Verifier is plain code. Numbers come from code (Analysis.values); the
fallback sentence is built from those values only.
"""

import json
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
from agents.pipeline.verifier import untranslated, verify
from core.contracts import Insight, Overlay
from core.contracts.overlay import OverlayTime

MAX_ATTEMPTS = 3  # the first line + 2 retries
LOCALIZER_ATTEMPTS = 2  # a translation + 1 retry
DURATION_MS = 6000


def values_of(task: NarrationTask) -> dict[str, float]:
    """Code-made numbers the line may quote: the moment's before/after metrics."""
    m = task.moment
    out = {f"{k}_before": v.value for k, v in m.metrics_before.items()}
    for k, v in m.metrics_after.items():
        out[f"{k}_after" if k in m.metrics_before else k] = v.value
    return out


def parse_insight(text: str, task: NarrationTask) -> Insight:
    """The Analyst's JSON; if it is not usable, a plain claim from code."""
    try:
        data = json.loads(text.strip().removeprefix("```json").removesuffix("```"))
        claim, mechanism = str(data["claim"]).strip(), str(data["mechanism"]).strip()
        confidence = min(1.0, max(0.0, float(data.get("confidence", 0.5))))
    except (ValueError, KeyError, TypeError):
        claim = f"{task.moment.kind.replace('_', ' ')}"
        mechanism, confidence = "See the numbers before and after.", 0.3
    return Insight(
        claim=claim or "-",
        mechanism=mechanism or "-",
        evidence_event_ids=task.moment.evidence_event_ids,
        confidence=confidence,
    )


class AnalystExecutor(Executor):
    def __init__(self, llm: LLMClient):
        super().__init__(id="analyst")
        self.agent = Agent(
            client=AdapterChatClient(llm), instructions=prompts.ANALYST, name="analyst"
        )

    @handler
    async def analyse(
        self, task: NarrationTask, ctx: WorkflowContext[Analysis]
    ) -> None:
        values = values_of(task)
        reply = await self.agent.run(prompts.analyst_prompt(task, values))
        insight = parse_insight(reply.text, task)
        await ctx.send_message(Analysis(task=task, insight=insight, values=values))


class NarratorExecutor(Executor):
    def __init__(self, llm: LLMClient):
        super().__init__(id="narrator")
        self.llm = llm
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
        reply = await self.agent(analysis.task.persona).run(
            prompts.narrator_prompt(analysis, reasons)
        )
        await ctx.send_message(
            Draft(
                analysis=analysis,
                text=reply.text.strip(),
                attempt=attempt,
                history=history,
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


class VerifierExecutor(Executor):
    """Plain code: pass -> Localizer; fail -> Retry (max 2); then fallback."""

    def __init__(self):
        super().__init__(id="verifier")

    @handler
    async def check(self, draft: Draft, ctx: WorkflowContext[Retry | Approved]) -> None:
        verdict = verify(
            draft.text, draft.analysis, examples(draft.analysis.task.persona)
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
        elif draft.attempt < MAX_ATTEMPTS:
            await ctx.send_message(
                Retry(
                    analysis=draft.analysis,
                    attempt=draft.attempt + 1,
                    reasons=verdict.reasons,
                    history=history,
                )
            )
        else:
            text = prompts.fallback(draft.analysis)
            await ctx.send_message(
                Approved(
                    analysis=draft.analysis,
                    text=text,
                    verdict=verify(text, draft.analysis),
                    fallback=True,
                    attempts=draft.attempt,
                    history=history,
                )
            )


class LocalizerExecutor(Executor):
    """Translates the approved line, checked by code (numbers unchanged, not
    still English); one retry with the reason, then the language is dropped
    (English always airs)."""

    def __init__(self, llm: LLMClient):
        super().__init__(id="localizer")
        self.llm = llm

    @handler
    async def localize(
        self, approved: Approved, ctx: WorkflowContext[None, Narration]
    ) -> None:
        task = approved.analysis.task
        text = {"en": approved.text}
        for lang in task.languages:
            agent = Agent(
                client=AdapterChatClient(self.llm),
                instructions=prompts.LOCALIZER.format(
                    language=prompts.LANGUAGE.get(lang, lang)
                ),
                name=f"localizer_{lang}",
            )
            ask = f"TEXT: {approved.text}"
            for _ in range(LOCALIZER_ATTEMPTS):
                reply = (await agent.run(ask)).text.strip()
                problem = untranslated(reply, approved.text)
                if problem is None:
                    text[lang] = reply
                    break
                ask = f"Your last reply was rejected: {problem}.\nTEXT: {approved.text}"
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


def build(llm: LLMClient):
    analyst = AnalystExecutor(llm)
    narrator = NarratorExecutor(llm)
    verifier = VerifierExecutor()
    localizer = LocalizerExecutor(llm)
    return (
        WorkflowBuilder(start_executor=analyst, max_iterations=20)
        .add_edge(analyst, narrator)
        .add_edge(narrator, verifier)
        .add_edge(verifier, narrator, condition=lambda msg: isinstance(msg, Retry))
        .add_edge(verifier, localizer, condition=lambda msg: isinstance(msg, Approved))
        .build()
    )


async def narrate(llm: LLMClient, task: NarrationTask) -> Narration:
    """Run the workflow for one moment and persona."""
    result = await build(llm).run(task)
    (out,) = result.get_outputs()
    return out


__all__ = ["MAX_ATTEMPTS", "Verdict", "build", "narrate", "values_of"]
