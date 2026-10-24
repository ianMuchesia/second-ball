"""Half-time and full-time recaps about one player (Phase 5: player focus).

Input is ONLY the player's stats at the whistle, counted by code
(core/players), each pre-phrased ("33 passes completed"). The model may
reword them for the persona; the Verifier checks it like any line (numbers,
names, counts said as given, no predictions), two retries, then a code
template in English and Kiswahili (templates.yaml, owner: Ian). With no
model (llm=None), the template is the recap.
"""

from dataclasses import dataclass
from typing import Literal

from agent_framework import Agent

from agents.llm import LLMClient
from agents.pipeline import prompts
from agents.pipeline.client import AdapterChatClient
from agents.pipeline.display import score_line, standing
from agents.pipeline.lineups import said
from agents.pipeline.models import Analysis, MatchContext, NarrationTask, Persona
from agents.pipeline.resilience import Policy, ask
from agents.pipeline.templates import LANGUAGES as TEMPLATE_LANGUAGES
from agents.pipeline.templates import wording
from agents.pipeline.verifier import check, verify
from agents.pipeline.workflow import UNAVAILABLE, localize
from core.contracts import Clock, Insight, LineupPlayer, MetricValue, Moment
from core.metrics import Events
from core.players import STATS, card_stats, contributions, total

When = Literal["half_time", "full_time"]
MAX_WORDS = 60
ATTEMPTS = 3

SYSTEM = """ROLE: PLAYER RECAP
You write the {when} recap of ONE player for the {persona} viewer.
{style}
At most 2 sentences and {max_words} words. Use only VALUES: his stats, each
said exactly as "say" gives it; name only him and his team; no predictions;
no judgement the numbers do not show."""


@dataclass
class Stats:
    """A player's card at the whistle: the stats with a value, in card order."""

    rows: dict[str, dict]  # stat name -> core.players.total(...)


def stats_at(events: Events, player: LineupPlayer, persona: Persona) -> Stats:
    parts = contributions(events, player.player_id, player.team_id)
    rows = {}
    for name in card_stats(player.position, persona):
        row = total(STATS[name], parts[name])
        if row["value"]:  # nothing to say about a zero: it is left out
            rows[name] = row
    return Stats(rows)


def pct(x: float) -> int:
    return round(100 * x)


def phrase(name: str, row: dict, lang: str) -> str:
    """One stat in words: '33 passes completed', 'pass completion 75% (...)'."""
    w = wording()["player"][lang]
    one, many = w["stats"][name]
    stat = STATS[name]
    if stat.rate:
        lo, hi = row["interval"]
        return w["rate"].format(
            label=one, pct=pct(row["value"]), lo=pct(lo), hi=pct(hi)
        )
    n = int(row["numerator"] if stat.of else row["value"])
    form = one if n == 1 else many
    return form.format(n=n, d=row["denominator"] or 0, v=f"{row['value']:.2f}")


def joined(parts: list[str], lang: str) -> str:
    if len(parts) < 2:
        return "".join(parts)
    word = " and " if lang == "en" else " na "
    return ", ".join(parts[:-1]) + word + parts[-1]


def template(
    when: When, task: NarrationTask, player: LineupPlayer, stats: Stats, lang="en"
):
    w = wording()["player"][lang]
    parts = [phrase(n, r, lang) for n, r in stats.rows.items()]
    return w["line"].format(
        when=w["when"][when],
        name=player.name,
        team=task.context.team_names[player.team_id],
        position=said(player),
        stats=joined(parts, lang) or w["none"],
    )


def player_task(
    when: When,
    events: Events,
    context: MatchContext,
    player: LineupPlayer,
    persona: Persona,
    languages: list[str],
) -> tuple[NarrationTask, dict[str, float], Stats]:
    stats = stats_at(events, player, persona)
    last = events.items[-1]
    metrics = {
        n: MetricValue(
            value=r["value"],
            evidence_event_ids=r["evidence_event_ids"] or [last.event_id],
            numerator=r["numerator"],
            denominator=r["denominator"],
        )
        for n, r in stats.rows.items()
    }
    values = {n: r["value"] for n, r in stats.rows.items()}
    counts = {}
    for n, r in stats.rows.items():
        if STATS[n].rate:
            values[f"{n}_low"], values[f"{n}_high"] = r["interval"]
        elif STATS[n].of:
            counts[n] = r["numerator"]
            counts[f"{n}_attempts"] = r["denominator"]
        elif STATS[n].unit != "xG":
            counts[n] = int(r["value"])
    evidence = list(
        dict.fromkeys(i for m in metrics.values() for i in m.evidence_event_ids)
    ) or [last.event_id]
    moment = Moment(
        moment_id=f"{context.match_id}-player-{player.player_id}-{when}",
        kind=f"player_recap_{when}",
        team=player.team_id,
        clock=Clock(period=last.period, minute=last.minute, second=last.second),
        importance=1.0,
        metrics_before={},
        metrics_after=metrics,
        evidence_event_ids=evidence,
    )
    ctx = context.model_copy(update={"minute": last.minute})
    task = NarrationTask(
        moment=moment,
        context=ctx,
        persona=persona,
        languages=languages,
        counts=counts,
        facts={
            "player": f"{player.name}, {ctx.team_names[player.team_id]}'s {said(player)}"
        },
        display={
            "score": score_line(ctx),
            "standing": standing(ctx),
            **{n: phrase(n, r, "en") for n, r in stats.rows.items()},
        },
    )
    return task, values, stats


async def player_recap(
    llm: LLMClient | None,
    when: When,
    events: Events,
    context: MatchContext,
    player: LineupPlayer,
    persona: Persona,
    languages: list[str] = (),
    policy: Policy | None = None,
) -> dict:
    """One verified recap paragraph about a player (a run-bundle row)."""
    policy = policy or Policy()
    task, values, stats = player_task(
        when, events, context, player, persona, list(languages)
    )
    analysis = Analysis(
        task=task,
        insight=Insight(
            claim=f"{player.name} at {when.replace('_', '-')}",
            mechanism="From his stats only.",
            evidence_event_ids=task.moment.evidence_event_ids,
            confidence=1.0,
        ),
        values=values,
    )
    final = when == "full_time"
    history, text = [], None
    if llm is not None:
        agent = Agent(
            client=AdapterChatClient(llm),
            instructions=SYSTEM.format(
                when=when.replace("_", "-"),
                persona=persona,
                style=prompts.STYLE[persona],
                max_words=MAX_WORDS,
            ),
            name=f"player_recap_{persona}",
        )
        for _ in range(ATTEMPTS):
            reasons = history[-1]["reasons"] if history else []
            fix = (
                ("\nYour last recap was rejected. Fix: " + "; ".join(reasons))
                if reasons
                else ""
            )
            reply = await ask(
                llm,
                agent,
                f"PLAYER: {task.facts['player']}\n"
                f"{prompts.values_block(task, values)}{fix}",
                "recap",
                policy,
            )
            if reply is None:
                history.append({"passed": False, "reasons": [UNAVAILABLE], "text": ""})
                break
            v = check(reply.strip(), analysis, max_words=MAX_WORDS, final=final)
            history.append(
                {
                    "passed": v.passed,
                    "reasons": v.reasons,
                    "text": v.text,
                    "fixes": v.fixes,
                }
            )
            if v.passed:
                text = v.text  # with any format fixes made in code
                break
    fallback = text is None
    if fallback:
        text = template(when, task, player, stats)
    verdict = verify(text, analysis, max_words=MAX_WORDS, final=final)
    # Without a model only the template languages exist (English, Kiswahili).
    languages = (
        task.languages
        if llm is not None
        else [x for x in task.languages if x in TEMPLATE_LANGUAGES]
    )
    translated = await localize(
        llm,
        policy,
        text,
        analysis,
        languages,
        templated=fallback,
        kind=lambda lang: template(when, task, player, stats, lang),
    )
    return {
        "player_id": player.player_id,
        "when": when,
        "persona": persona,
        "text": translated,
        "fallback": fallback,
        "passed": verdict.passed,
        "reasons": verdict.reasons,
        "attempts": len(history),
        "verdicts": history,
        "values": values,
        "evidence_event_ids": task.moment.evidence_event_ids,
    }
