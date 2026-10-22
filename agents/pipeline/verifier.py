"""Verifier: plain code checks every number and name in a draft line.

- Every number must match one of the Insight's values (with the rounding the
  line uses, e.g. "0.7" or "71%" for 0.712) or the match context (score,
  minutes, players on the pitch, shirt numbers).
- Every capitalised name must be a team or a player on the pitch.
- Rejected outright: predictions ("will win"), and blaming one event on the
  weather.
- Saying the wrong team leads (or trails) is rejected: the score decides.
- A line too close to one of the style examples is rejected (copied).
- Injuries and the referee are not rejected but raise the risk tier to high:
  a human must approve before the line airs.
Returns a Verdict: passed, or the list of reasons (fed back to the Narrator).
`untranslated` checks the Localizer's reply the same way: plain code.
"""

import re
from collections.abc import Sequence

from agents.pipeline.models import Analysis, Verdict

NUMBER = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)(\s*%|\s*per\s*cent)?", re.IGNORECASE)
WORD = re.compile(r"[A-Za-z][A-Za-z'\-]*")
PREDICTION = re.compile(
    r"\b(will|going to|gonna|bound to|certain to|sure to|set to)\s+"
    r"(win|lose|score|concede|draw|go on|take|come back|hold on)",
    re.IGNORECASE,
)
WEATHER_CAUSE = re.compile(
    r"\b(because of|due to|thanks to|blame|caused by|the)\s+(the\s+)?"
    r"(rain|wind|heat|weather|sun|pitch conditions)\b.*?\b(made|caused|led to|meant|so)\b"
    r"|\b(because of|due to|caused by|blame[sd]?( it)? on)\s+(the\s+)?"
    r"(rain|wind|heat|weather)\b",
    re.IGNORECASE,
)
RISKY = re.compile(
    r"\b(injur\w*|hamstring|knock|limping|stretcher|referee|ref|VAR|"
    r"linesman|officials?|dive|diving|harsh|robbed)\b",
    re.IGNORECASE,
)
# Capitalised words that are not names (sentence openers included). A word
# outside this list and outside the teams and players on the pitch is treated
# as a name: the Verifier would rather send a line back than air an invented
# player. Extend it when a real model's openers are wrongly rejected.
COMMON_WORDS = """
    a an the and but or so yet what that this these those it its they them their
    there here he him his she her we our you your now then again once twice still
    just only even also already almost nearly quite really simply suddenly finally
    another every each both all more most less much many few no not yes oh wow look
    is was were are be been has have had can could should would may might must do did
    in on at by for of to from into onto behind through over under off out up down
    after before with without while when where why how who which as if because since
    until though although than very too
    goal goals red card cards counter counters chance chances minute minutes half time
    first second third late early back ten nine eleven one two three four five
    control pressure momentum possession threat shape block line lines press pressing
    space openness game match end ball pass passes shot shots save saves cross
    corner free kick break breaks attack attacks defence defense keeper winger
    full fullback full-back striker midfield centre center left right wide deep high
    big huge great brilliant superb lovely clinical quick fast sharp clever simple
    unbelievable incredible remarkable another familiar same pattern again lightning
    home away side sides team teams players player everyone nobody somebody
    """
COMMON = set(COMMON_WORDS.split())
LEADS = r"(?:'s)?\s+(?:are\s+|now\s+|still\s+)?(lead|leads|leading|ahead|in front)\b"
TRAILS = r"(?:'s)?\s+(?:are\s+|now\s+|still\s+)?(trail|trails|trailing)\b"
COPY_LIMIT = 0.8  # word overlap (Jaccard) with a style example that counts as a copy
# Common English words that should not survive a translation; 2 or more means
# the Localizer answered (partly) in English.
ENGLISH_HINTS = {"the", "and", "behind", "from", "with", "their", "again", "is"}


def numbers(text: str) -> list[tuple[float, int, bool]]:
    """(value, decimals, is_percent) for every number in the text."""
    out = []
    for m in NUMBER.finditer(text):
        raw = m.group(1)
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        out.append((float(raw), decimals, bool(m.group(2))))
    return out


def allowed_numbers(analysis: Analysis) -> list[float]:
    ctx = analysis.task.context
    moment = analysis.task.moment
    shirts = [
        float(pid.rsplit("-", 1)[-1])
        for pid in ctx.players
        if pid.rsplit("-", 1)[-1].isdigit()
    ]
    on_pitch = [
        float(sum(1 for pid in ctx.players if pid.startswith(team + "-")))
        for team in (ctx.home, ctx.away)
    ]
    return [
        *analysis.values.values(),
        *ctx.score,
        float(ctx.minute),
        float(moment.clock.minute),
        *shirts,
        *on_pitch,
    ]


def matches(x: float, decimals: int, percent: bool, v: float) -> bool:
    """x as written (with its rounding) is v, or v as a percentage."""
    tol = 0.5 * 10**-decimals + 1e-9
    candidates = [v, v * 100] if percent or abs(v) <= 1 else [v]
    return any(abs(x - c) <= tol for c in candidates)


def known_names(analysis: Analysis) -> set[str]:
    ctx = analysis.task.context
    words = set()
    for name in [*ctx.team_names.values(), *ctx.players.values(), ctx.home, ctx.away]:
        words |= {w.lower() for w in WORD.findall(name.replace("_", " "))}
    return words


def unknown_names(text: str, analysis: Analysis) -> list[str]:
    known = known_names(analysis)
    out = []
    for sentence in re.split(r"(?<=[.!?:;])\s+|\n", text):
        for m in WORD.finditer(sentence):
            w = re.sub(r"'s?$", "", m.group(0))  # Riverside's -> Riverside
            if not w[0].isupper() or w.isupper():
                continue  # lower case, or an acronym (xG, PPDA)
            if w.lower() not in known and w.lower() not in COMMON:
                out.append(w)
    return out


def score_mistakes(text: str, analysis: Analysis) -> list[str]:
    """'X lead', 'X trailing', 'leading X' etc. checked against the score."""
    ctx = analysis.task.context
    home, away = ctx.score
    leader = ctx.home if home > away else ctx.away if away > home else None
    claims = []  # (team, leads?)
    for team in (ctx.home, ctx.away):
        other = ctx.away if team == ctx.home else ctx.home
        name = re.escape(ctx.team_names[team])
        if re.search(rf"\b{name}{LEADS}", text, re.IGNORECASE):
            claims.append((team, True))
        if re.search(rf"\b{name}{TRAILS}", text, re.IGNORECASE):
            claims.append((team, False))
        if re.search(rf"\bleading\s+{name}\b", text, re.IGNORECASE):
            claims.append((other, True))
        if re.search(rf"\btrailing\s+{name}\b", text, re.IGNORECASE):
            claims.append((other, False))
    score = f"{ctx.team_names[ctx.home]} {home}-{away} {ctx.team_names[ctx.away]}"
    return [
        f"wrong about the score: it is {score}, so {ctx.team_names[team]} "
        f"{'do not lead' if leads else 'are not behind'}"
        for team, leads in claims
        if (leader == team) != leads
    ]


def words_of(text: str) -> set[str]:
    return {w.lower() for w in WORD.findall(text)}


def copied(text: str, examples: Sequence[str]) -> bool:
    mine = words_of(text)
    for line in examples:
        theirs = words_of(line)
        if mine and len(mine & theirs) / len(mine | theirs) > COPY_LIMIT:
            return True
    return False


def untranslated(translation: str, english: str) -> str | None:
    """Why a translation is not usable, or None. Numbers are checked too."""
    if not translation:
        return "empty reply"
    if translation.strip().lower() == english.strip().lower():
        return "the reply is the English line, not a translation"
    if len(words_of(translation) & ENGLISH_HINTS) >= 2:
        return "the reply is still partly English"
    if sorted(x for x, _, _ in numbers(translation)) != sorted(
        x for x, _, _ in numbers(english)
    ):
        return "the numbers changed; keep every number exactly as written"
    return None


def verify(text: str, analysis: Analysis, examples: Sequence[str] = ()) -> Verdict:
    """`examples`: the Narrator's style examples, which a line must not copy."""
    reasons = []
    allowed = allowed_numbers(analysis)
    for x, decimals, percent in numbers(text):
        if not any(matches(x, decimals, percent, v) for v in allowed):
            shown = f"{x:g}{'%' if percent else ''}"
            reasons.append(
                f"number {shown} is not in the values or the match context; "
                f"use only: {', '.join(f'{k}={v:g}' for k, v in analysis.values.items())}"
            )
    for name in unknown_names(text, analysis):
        reasons.append(f"'{name}' is not a team or a player on the pitch")
    reasons += score_mistakes(text, analysis)
    if copied(text, examples):
        reasons.append("too close to a style example: write your own line")
    if PREDICTION.search(text):
        reasons.append("no predictions: describe what happened, not what will happen")
    if WEATHER_CAUSE.search(text):
        reasons.append("do not blame a single event on the weather")
    risky = bool(RISKY.search(text))
    return Verdict(
        passed=not reasons, reasons=reasons, risk_tier="high" if risky else "low"
    )
