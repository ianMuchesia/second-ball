"""Code templates: broadcast sentences per moment kind and persona, in English
and Kiswahili, filled only with code values (the wording is in
templates.yaml, owner: Ian). They air when the model gives no answer or every
draft is rejected, and the Verifier checks them like any line.
"""

from functools import cache
from pathlib import Path

import yaml

from agents.pipeline.display import shown
from agents.pipeline.models import Analysis, NarrationTask
from agents.pipeline.prompts import KIND_WORDS, metric

LANGUAGES = ("en", "sw")  # templates exist in these; others go to the Localizer


@cache
def wording() -> dict:
    return yaml.safe_load((Path(__file__).with_name("templates.yaml")).read_text())


def standing(task: NarrationTask, lang: str) -> str:
    ctx, w = task.context, wording()[lang]["standing"]
    home, away = ctx.score
    if home == away:
        return w["level"].format(a=home, b=away)
    lead = ctx.home if home > away else ctx.away
    return w["lead"].format(
        team=ctx.team_names[lead], a=max(home, away), b=min(home, away)
    )


def num(v: float) -> str:
    x = shown(v)
    if isinstance(x, int):
        return str(x)
    # 1.003 rounds to "1.00": written whole, as the Verifier's style wants.
    return f"{x:.2f}".removesuffix(".00")


def changes(values: dict[str, float], lang: str, limit: int = 2) -> str:
    """'Control index 0.71 to 0.80, ...' from the before/after pairs."""
    w = wording()[lang]
    out = []
    for k, before in values.items():
        name = k.removesuffix("_before")
        if name == k or f"{name}_after" not in values:
            continue
        if lang == "en":
            m = metric(name)
            label = m.display_name["analyst"] if m else name.replace("_", " ")
            # Mid-sentence: lower case, except an acronym (xG, PPDA).
            first = label.split()[0]
            if not (first.isupper() or first[1:2].isupper()):
                label = label[0].lower() + label[1:]
        elif name in w["metric"]:
            label = w["metric"][name]
        else:
            continue  # no Kiswahili name yet: leave it out rather than mix
        out.append(
            w["change"].format(
                metric=label, a=num(before), b=num(values[f"{name}_after"])
            )
        )
    return ", ".join(out[:limit])


def red_card_player(task: NarrationTask):
    """The sent-off player, from the team sheet (named in the code-made facts)."""
    said = task.facts.get("sent_off", "")
    return next((p for p in task.context.lineup if p.name in said), None)


def template(analysis: Analysis, lang: str = "en") -> str:
    task, values = analysis.task, analysis.values
    ctx, w = task.context, wording()[lang]
    kind, persona = task.moment.kind, task.persona
    team_id = task.moment.team
    team = ctx.team_names.get(team_id or "", "")
    other_id = ctx.away if team_id == ctx.home else ctx.home
    fill = {
        "minute": task.moment.clock.minute,
        "team": team,
        "standing": standing(task, lang),
        "score": task.display.get("score", ""),
    }
    if kind == "goal":
        how = ""
        if task.facts.get("build_up") == "counter-attack":
            side = task.facts.get("side", "")
            zone = w["zone"].format(
                other=ctx.team_names[other_id],
                side=w.get("side", {}).get(side, side),
            )
            how = w["goal"]["counter"].format(zone=zone)
        # No "before" for the team's first chance: nothing came before it.
        before = (
            w["goal"]["before"].format(before=f"{values['xg_before']:.2f}")
            if "xg_before" in values
            else ""
        )
        # No chance number (an own goal has no shot): the plain sentence.
        line = w["goal"][persona if "shot_xg" in values else "casual"]
        return line.format(
            **fill,
            how=how,
            chance=f"xG {values.get('shot_xg', 0):.2f}",
            before=before,
        )
    if kind == "big_chance":
        chance = (
            f"xG {values['shot_xg']:.2f}"
            if persona == "analyst"
            else task.display.get("chance", "")
        )
        return w["big_chance"][persona].format(**fill, chance=chance)
    if kind == "red_card_impact":
        p = red_card_player(task)
        reason = w["red_card_impact"]["reason"].get(task.facts.get("reason", ""), "")
        if persona == "casual" or not changes(values, lang):
            line = w["red_card_impact"]["casual"]
        else:
            line = w["red_card_impact"]["analyst"]
        return line.format(
            **fill,
            name=p.name if p else team,
            shirt=p.shirt_number if p else "",
            reason=reason,
            changes=changes(values, lang),
        )
    found = changes(values, lang)
    words = KIND_WORDS.get(kind, kind.replace("_", " "))
    if not team:  # a match-wide moment (the game opening up): no team
        line, words = w["other"]["match"], words[0].upper() + words[1:]
    else:
        line = w["other"]["analyst" if persona == "analyst" and found else "casual"]
    return line.format(
        **fill,
        kind=w["kind"].get(kind, kind.replace("_", " ").upper()),
        words=words,
        changes=found,
    )


def recap_template(when: str, task: NarrationTask, values, lang: str = "en") -> str:
    """'HALF-TIME. Riverside 0-1 Harbour. Shots: Riverside 13, Harbour 3.'"""
    ctx, w = task.context, wording()[lang]["recap"]
    home, away = ctx.team_names[ctx.home], ctx.team_names[ctx.away]
    stat = ""
    key = "shots" if task.persona == "casual" else "xg"
    a = values.get(f"{home.lower().replace(' ', '_')}_{key}")
    b = values.get(f"{away.lower().replace(' ', '_')}_{key}")
    if a is not None and b is not None:
        stat = w["stat"][task.persona].format(
            home=home,
            away=away,
            home_shots=num(a),
            away_shots=num(b),
            home_xg=f"{a:.2f}",
            away_xg=f"{b:.2f}",
        )
    text = w[when].format(score=task.display.get("score", ""), stat=stat)
    return text.replace(". .", ".")
