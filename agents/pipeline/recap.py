"""Half-time and full-time recaps.

Input is ONLY what already aired (lines the Verifier passed) and the
MatchState at the whistle (code-made stats). The recap is checked by the same
Verifier (numbers: the stats and the aired lines' values; names; who leads;
counts; at half-time no predictions; at full time "sealed the win" is a fact),
retried twice, then a code template. Saved like any overlay, with evidence.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from agent_framework import Agent

from agents.llm import LLMClient
from agents.pipeline import prompts
from agents.pipeline.client import AdapterChatClient
from agents.pipeline.display import score_line, standing
from agents.pipeline.models import (
    Analysis,
    MatchContext,
    Narration,
    NarrationTask,
    Persona,
    Verdict,
)
from agents.pipeline.resilience import Policy, ask
from agents.pipeline.templates import recap_template
from agents.pipeline.verifier import verify
from agents.pipeline.workflow import UNAVAILABLE, localize
from agents.telemetry import step
from core.contracts import Insight, MetricValue, Moment, Overlay
from core.contracts.overlay import OverlayTime
from core.metrics import Events, match_state

When = Literal["half_time", "full_time"]
RECAP_METRICS = ["xg", "shots", "big_chances"]
MAX_WORDS = 60
ATTEMPTS = 3
DURATION_MS = 15000
WORDS = {"half_time": "Half-time", "full_time": "Full-time"}

SYSTEM = """ROLE: RECAP
You write the {when} recap of a football match for the {persona} viewer.
{style}
At most 3 sentences and {max_words} words. Use only what is in AIRED (lines
that already aired) and VALUES; quote only numbers from VALUES or AIRED; name
only the teams. {rule}"""
RULE = {
    "half_time": "The match is not over: no predictions.",
    "full_time": "The match is over: say how it ended; nothing about what comes next.",
}


@dataclass
class Aired:
    """A line that aired, with the task it was made from (its counts)."""

    overlay: Overlay
    task: NarrationTask


def slug(name: str) -> str:
    return name.lower().replace(" ", "_")


def stat_phrases(ctx: MatchContext, stats: dict[str, MetricValue]) -> dict:
    """Recap counts with what they count: "Riverside's 13 shots"."""
    out = {}
    for team in (ctx.home, ctx.away):
        name = ctx.team_names[team]
        for metric, noun in (("shots", "shot"), ("big_chances", "big chance")):
            mv = stats.get(f"{slug(name)}_{metric}")
            if mv is not None:
                n = int(mv.value)
                out[f"{slug(name)}_{metric}"] = (
                    f"{name}'s {n} {noun}{'' if n == 1 else 's'}"
                )
    return out


def recap_task(
    when: When,
    events: Events,
    context: MatchContext,
    aired: list[Aired],
    persona: Persona,
    languages: list[str],
) -> tuple[NarrationTask, dict[str, float]]:
    """The recap as a match-wide moment: stats from the MatchState as its
    values, plus the aired lines' values (so the recap may quote them)."""
    state = match_state(events)
    stats: dict[str, MetricValue] = {}
    for team in (context.home, context.away):
        for name in RECAP_METRICS:
            mv = state.metrics.get(team, {}).get(name)
            if mv is not None:
                stats[f"{slug(context.team_names[team])}_{name}"] = mv
    evidence = list(
        dict.fromkeys(
            [i for a in aired for i in a.overlay.evidence_event_ids]
            + [i for mv in stats.values() for i in mv.evidence_event_ids]
            + [events.items[-1].event_id]
        )
    )
    moment = Moment(
        moment_id=f"{context.match_id}-recap-{when}",
        kind=f"recap_{when}",
        team=None,
        clock=state.clock,
        importance=1.0,
        metrics_before={},
        metrics_after=stats,
        evidence_event_ids=evidence,
    )
    counts: dict[str, int] = {}
    for a in aired:
        for k, v in a.task.counts.items():
            counts[k] = max(counts.get(k, v), v)
    counts.pop("passes_in_move", None)  # about one move, not the match
    ctx = context.model_copy(update={"minute": state.clock.minute})
    task = NarrationTask(
        moment=moment,
        context=ctx,
        persona=persona,
        languages=languages,
        counts=counts,
        display={
            "score": score_line(ctx),
            "standing": standing(ctx),
            **stat_phrases(ctx, stats),
        },
    )
    values = {k: mv.value for k, mv in stats.items()}
    for i, a in enumerate(aired):
        values |= {f"aired{i}_{k}": v for k, v in a.overlay.values.items()}
    return task, values


def fallback(when: When, task: NarrationTask, values, aired: list[Aired]) -> str:
    """The English code template: score and one stat (templates.yaml)."""
    return recap_template(when, task, values, "en")


def prompt(task: NarrationTask, values, aired: list[Aired], reasons) -> str:
    lines = "\n".join(
        f"- {a.overlay.t_in.match.minute}': {a.overlay.text['en']}"
        for a in aired
        if a.task.persona == task.persona
    )
    fix = (
        ("\nYour last recap was rejected. Fix: " + "; ".join(reasons))
        if reasons
        else ""
    )
    return (
        f"AIRED:\n{lines or '- (nothing aired yet)'}\n"
        f"{prompts.values_block(task, values)}{fix}"
    )


async def recap(
    llm: LLMClient,
    when: When,
    events: Events,
    context: MatchContext,
    aired: list[Aired],
    persona: Persona,
    languages: list[str] = (),
    policy: Policy | None = None,
) -> Narration:
    policy = policy or Policy()
    task, values = recap_task(when, events, context, aired, persona, list(languages))
    analysis = Analysis(
        task=task,
        insight=Insight(
            claim=f"{WORDS[when]} recap",
            mechanism="From aired lines and match stats only.",
            evidence_event_ids=task.moment.evidence_event_ids,
            confidence=1.0,
        ),
        values=values,
    )
    agent = Agent(
        client=AdapterChatClient(llm),
        instructions=SYSTEM.format(
            when=WORDS[when].lower(),
            persona=persona,
            style=prompts.STYLE[persona],
            max_words=MAX_WORDS,
            rule=RULE[when],
        ),
        name=f"recap_{persona}",
    )
    final = when == "full_time"
    history: list[Verdict] = []
    text = None
    with step("recap", when=when, persona=persona) as span:
        for attempt in range(1, ATTEMPTS + 1):
            reasons = history[-1].reasons if history else []
            reply = await ask(
                llm, agent, prompt(task, values, aired, reasons), "recap", policy
            )
            if reply is None:
                history.append(Verdict(passed=False, reasons=[UNAVAILABLE]))
                break
            with step("verifier", attempt=attempt) as v_span:
                verdict = verify(
                    reply.strip(), analysis, max_words=MAX_WORDS, final=final
                ).model_copy(update={"text": reply.strip()})
                v_span.set_attributes(
                    {"passed": verdict.passed, "reasons": verdict.reasons}
                )
            history.append(verdict)
            if verdict.passed:
                text = reply.strip()
                break
        is_fallback = text is None
        if is_fallback:
            text = fallback(when, task, values, aired)
        verdict = verify(text, analysis, max_words=MAX_WORDS, final=final)
        span.set_attributes({"fallback": is_fallback, "attempts": len(history)})
        translated = await localize(
            llm,
            policy,
            text,
            analysis,
            task.languages,
            templated=is_fallback,
            kind=lambda lang: recap_template(when, task, values, lang),
        )
    overlay = Overlay(
        overlay_id=f"{task.moment.moment_id}-{persona}",
        match_id=context.match_id,
        kind=task.moment.kind,
        slot="recap",
        t_in=OverlayTime(match=task.moment.clock, wall=datetime.now(UTC)),
        duration_ms=DURATION_MS,
        priority=100,
        risk_tier=verdict.risk_tier,
        text=translated,
        values={k: v for k, v in values.items() if not k.startswith("aired")},
        evidence_event_ids=task.moment.evidence_event_ids,
        status="pending",
    )
    return Narration(
        overlay=overlay,
        fallback=is_fallback,
        attempts=len(history),
        verdicts=history,
        insight=analysis.insight,
    )
