"""Prompts and the fallback template. Every number shown to a model comes from
code (the VALUES block); the model only chooses words."""

import json

from agents.narrator import examples
from agents.pipeline.models import Analysis, MatchContext, NarrationTask

KIND_WORDS = {
    "goal": "goal",
    "red_card_impact": "the red card's effect",
    "big_chance": "big chance",
    "momentum_swing": "momentum swings their way",
    "repeated_pattern": "the same pattern again",
    "control_shift": "taking control",
    "pressure_spike": "pressing harder",
    "shape_change": "a change of shape",
    "openness_spike": "the game opens up",
    "overload": "outnumbering them near the ball",
    "bad_situation": "in trouble on the ball",
    "player_milestone": "a milestone",
}

ANALYST = """ROLE: ANALYST
You explain why a football moment happened, for a live broadcast. Use only the
numbers in VALUES; never compute, estimate or invent a number. Reply with JSON
only: {"claim": "<one sentence: what happened>", "mechanism": "<one sentence:
why, in football terms>", "confidence": <0-1>}."""

NARRATOR = """ROLE: NARRATOR
You write ONE on-screen line (max 25 words) about a football moment for the
{persona} viewer. {style}
Rules: quote only numbers from VALUES (you may round them); name only the teams
and players listed; "standing" says who is leading, "good_for" who the
moment helps and "numbers_are_for" whose numbers they are, so never say
otherwise; no predictions; do not blame one event
on the weather; no injury or referee talk."""

STYLE = {
    "casual": "Casual fan: short, a little emotion, plain words, no jargon.",
    "analyst": "Analyst: precise, with the number and the why.",
}

LOCALIZER = """ROLE: LOCALIZER
Translate the line into {language}. Keep every number exactly as written and
keep team and player names unchanged. Use football meanings: "clinical" means
accurate and deadly in front of goal, never medical. Reply with the
translation only."""

# What happened, in words code chooses, so a model cannot get the sides wrong.
EVENT = {
    "goal": "{team} scored",
    "red_card_impact": "{team} had a player sent off",
}
# Who the moment is good for: the team itself, or its opponent.
GOOD_FOR_OPPONENT = {"red_card_impact"}

LANGUAGE = {"sw": "Swahili"}


def standing(ctx: MatchContext, team: str) -> str:
    """'leading', 'trailing' or 'level', plus 'a player down' (or more)."""
    home, away = ctx.score
    mine, theirs = (home, away) if team == ctx.home else (away, home)
    words = "leading" if mine > theirs else "trailing" if mine < theirs else "level"
    other = ctx.away if team == ctx.home else ctx.home
    down = ctx.sent_off.get(team, 0) - ctx.sent_off.get(other, 0)
    if down > 0:
        words += ", a player down" if down == 1 else f", {down} players down"
    return words


def values_block(task: NarrationTask, values: dict[str, float]) -> str:
    ctx = task.context
    team = task.moment.team
    name = ctx.team_names.get(team or "", None)
    block = {
        "kind": task.moment.kind,
        "team": name,
        "minute": task.moment.clock.minute,
        "score": f"{ctx.team_names[ctx.home]} {ctx.score[0]}-{ctx.score[1]} "
        f"{ctx.team_names[ctx.away]}",
        "standing": {ctx.team_names[t]: standing(ctx, t) for t in (ctx.home, ctx.away)},
        "numbers": {k: round(v, 2) for k, v in values.items()},
        "numbers_are_for": name or "the match",
        "players_on_pitch": sorted(ctx.players.values()),
    }
    if team and task.moment.kind in EVENT:
        other = ctx.away if team == ctx.home else ctx.home
        block["event"] = EVENT[task.moment.kind].format(team=name)
        good = other if task.moment.kind in GOOD_FOR_OPPONENT else team
        block["good_for"] = ctx.team_names[good]
    return "VALUES: " + json.dumps(block)


def analyst_prompt(task: NarrationTask, values: dict[str, float]) -> str:
    return f"Moment: {task.moment.kind}.\n{values_block(task, values)}"


def narrator_system(persona: str) -> str:
    shots = examples(persona)
    tail = (
        (
            "\nSTYLE EXAMPLES ONLY - DO NOT COPY PHRASING OR NUMBERS FROM THESE "
            "EXAMPLES (they are other moments):\n" + "\n".join(f"- {x}" for x in shots)
        )
        if shots
        else ""
    )
    return NARRATOR.format(persona=persona, style=STYLE[persona]) + tail


def narrator_prompt(analysis: Analysis, reasons: list[str]) -> str:
    fix = (
        ("\nYour last line was rejected. Fix: " + "; ".join(reasons)) if reasons else ""
    )
    return (
        f"Claim: {analysis.insight.claim}\nWhy: {analysis.insight.mechanism}\n"
        f"{values_block(analysis.task, analysis.values)}{fix}"
    )


def fallback(analysis: Analysis) -> str:
    """A plain sentence built only from code values (used after 2 failed retries)."""
    task = analysis.task
    ctx = task.context
    who = ctx.team_names.get(task.moment.team or "", "The match")
    words = KIND_WORDS.get(task.moment.kind, task.moment.kind.replace("_", " "))
    pairs = [
        (
            name[: -len("_before")],
            v,
            analysis.values.get(name[: -len("_before")] + "_after"),
        )
        for name, v in analysis.values.items()
        if name.endswith("_before")
    ]
    detail = ""
    if pairs and pairs[0][2] is not None:
        name, before, after = pairs[0]
        detail = f" {name.replace('_', ' ')} {before:.2f} to {after:.2f}."
    return f"{who}, {task.moment.clock.minute}': {words}.{detail}"
