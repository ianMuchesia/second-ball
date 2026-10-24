"""How numbers are written on screen, decided by code, never by the model.

The facts about a moment are the same for every viewer; only how they are
written differs (fan or analyst). A line quotes these strings as given:

- scores in digits, home first: "Riverside 0-1 Harbour"; the standing leader
  first: "Harbour lead 1-0" ("level at 0-0"); never "zero to one"
- counts as whole numbers: "13 shots", never "13.0"
- a chance as "xG 0.45" for analysts, in words for fans ("a big chance")
- a count with its meaning: "Harbour's second goal on the counter", "1 pass
  in the move", "Riverside's 13 shots"; a line uses it as given, so the model
  cannot attach it to the wrong thing ("one counter creates 2 goals")
"""

from agents.mcp_server.data import MatchData
from agents.pipeline.models import MatchContext, Persona
from core.contracts import Moment
from core.moments import config as moment_config

# A fan's words for one chance by its xG. TUNABLE, owner: Ian. The big-chance
# line is the detector's (core/moments/config.yaml); below it, "good" from here.
GOOD_CHANCE_XG = 0.15
CHANCE_KINDS = {"goal", "big_chance"}


def score_line(ctx: MatchContext) -> str:
    home, away = ctx.score
    return f"{ctx.team_names[ctx.home]} {home}-{away} {ctx.team_names[ctx.away]}"


def standing(ctx: MatchContext) -> str:
    """The leader and their score first: 'Harbour lead 1-0', or 'level at 1-1'."""
    home, away = ctx.score
    if home == away:
        return f"level at {home}-{away}"
    lead, (a, b) = (ctx.home, (home, away)) if home > away else (ctx.away, (away, home))
    return f"{ctx.team_names[lead]} lead {a}-{b}"


def chance_words(xg: float) -> str:
    big = moment_config()["big_chance"]["xg"]
    if xg >= big:
        return "a big chance"
    return "a good chance" if xg >= GOOD_CHANCE_XG else "a half-chance"


def shot_xg(data: MatchData, moment: Moment) -> float | None:
    """The xG of the shot a goal or chance is about (its last evidence event)."""
    if moment.kind not in CHANCE_KINDS:
        return None
    by_id = {e.event_id: e for e in data.events.items}
    for i in reversed(moment.evidence_event_ids):
        e = by_id.get(i)
        if e is not None and e.qualifiers.get("xg") is not None:
            return float(e.qualifiers["xg"])
    return None


ORDINAL_WORDS = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth"}


def count_phrases(counts: dict[str, int], team: str | None) -> dict[str, str]:
    """Each count with what it counts (keys match NarrationTask.counts)."""
    out = {}
    n = counts.get("counter_goals")
    if n and team:
        out["counter_goals"] = (
            f"{team}'s {ORDINAL_WORDS.get(n, f'{n}th')} goal on the counter"
        )
    n = counts.get("passes_in_move")
    if n is not None:
        out["passes_in_move"] = f"{n} pass{'' if n == 1 else 'es'} in the move"
    return out


def display_for(
    data: MatchData,
    moment: Moment,
    ctx: MatchContext,
    persona: Persona,
    counts: dict[str, int] | None = None,
) -> dict[str, str]:
    out = {"score": score_line(ctx), "standing": standing(ctx)}
    out |= count_phrases(counts or {}, ctx.team_names.get(moment.team or ""))
    xg = shot_xg(data, moment)
    if xg is not None:
        out["chance"] = f"xG {xg:.2f}" if persona == "analyst" else chance_words(xg)
    return out


def shown(v: float) -> float | int:
    """A value as the model sees it: counts whole, other numbers to 2 places."""
    return int(v) if float(v).is_integer() else round(v, 2)
