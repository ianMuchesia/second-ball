"""Verifier: plain code checks every number and name in a draft line.

- Every number must match one of the Insight's values (with the rounding the
  line uses, e.g. "0.7" or "71%" for 0.712) or the match context (score,
  minutes, players on the pitch, shirt numbers).
- Counts written as words or digits before a football noun ("one pass",
  "ten men", "second counter goal", "twice") must match a code-made count of
  that kind (passes in the move, players on the pitch, goals, counters).
- Comparisons ("halved", "doubled", "up by a third") must be within 10% of a
  real before/after change (Ian, 2026-10-22).
- Casual lines show no raw index numbers: no decimals at all.
- Every capitalised name must be a team or a player on the team sheet; a
  position, playing style or shirt number said with a player's name must
  match the sheet ("left-back Lindqvane", "number 5 Stonebridge").
- "Last man" only when code found a last-man foul (facts["reason"]).
- Rejected outright: predictions ("will win", and soft ones that treat the
  match as over: "seal it", "secure the 0-2", "game over"), and blaming one
  event on the weather.
- When code says how a goal was made (facts: build_up, side), the line must
  name the counter and the side.
- Saying the wrong team leads (or trails) is rejected: the score decides.
- Giving one team's numbers (control, xG) to the other is rejected.
- A line too close to one of the style examples is rejected (copied).
- Injuries and the referee are not rejected but raise the risk tier to high:
  a human must approve before the line airs.
Returns a Verdict: passed, or the list of reasons (fed back to the Narrator).
`untranslated` checks the Localizer's reply the same way: plain code.
"""

import re
from collections.abc import Sequence

from agents.pipeline.display import score_line
from agents.pipeline.lineups import (
    CLAIMS,
    STYLE_OF,
    STYLE_WORDS,
    name_pattern,
)
from agents.pipeline.models import Analysis, Verdict

NUMBER = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)(\s*%|\s*per\s*cent)?", re.IGNORECASE)
WORD = re.compile(r"[A-Za-z][A-Za-z'\-]*")
PREDICTION = re.compile(
    r"\b(will|going to|gonna|bound to|certain to|sure to|set to)\s+"
    r"(win|lose|score|concede|draw|go on|take|come back|hold on)",
    re.IGNORECASE,
)
# Finality verbs and idioms: the clock is still running.
SOFT_PREDICTIONS = [
    (
        r"\b(seal|seals|sealed|sealing)\s+"
        r"(it|the\s+(win|game|match|points|victory|result|\d+-\d+))\b"
    ),
    (
        r"\b(secure|secures|secured|securing)\s+"
        r"(it|the\s+(win|game|match|points|victory|result|\d+-\d+))\b"
    ),
    r"\b(wrap|wraps|wrapped)\s+(it\s+up|up\s+the\s+(win|points|game|match|victory))\b",
    (
        r"\b(put|puts|putting)\s+(it|the\s+game|the\s+match|the\s+result)\s+"
        r"(to\s+bed|beyond\s+doubt|out\s+of\s+reach)\b"
    ),
    (
        r"\b(clinch|clinches|clinched|lock\s+in|locks\s+in)\s+"
        r"(it|the\s+(win|points|victory|match))\b"
    ),
    r"\b(bag|bags|bagged)\s+the\s+(win|points|victory)\b",
    (
        r"\b(game\s+over|all\s+over|done\s+and\s+dusted|no\s+way\s+back|"
        r"unassailable|insurmountable|surely\s+won|that\s+is\s+that|that's\s+that|"
        r"knockout\s+blow|killer\s+blow|nail\s+in\s+the\s+coffin|coup\s+de\s+gr[aâ]ce)\b"
    ),
]
SOFT_PREDICTION = re.compile("|".join(SOFT_PREDICTIONS), re.IGNORECASE)
COUNTER_WORDS = re.compile(
    r"\b(counter|counters|counter-attack|counterattack|break|breakaway)\b",
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
    leading trailing level down half-time full-time halftime fulltime kick-off
    whistle recap shots xg number no captain
    home away side sides team teams players player everyone nobody somebody
    """
COMMON = set(COMMON_WORDS.split())
# "Harbour lead", "Harbour are leading": the team is the subject. A bare
# participle ("against Harbour trailing 0-1") is not read as a claim, nor is
# "behind" (that is usually space: "behind the left-back").
LEADS = r"(?:'s)?\s+(?:(?:now|still)\s+)?(lead|leads|ahead|in\s+front|(?:are|is)\s+(?:now\s+|still\s+)?leading)\b"
TRAILS = r"\s+(?:(?:now|still)\s+)?(trail|trails|(?:are|is)\s+(?:now\s+|still\s+)?trailing)\b"
# Metrics that belong to one team: "Harbour's control" when the numbers are
# Riverside's is wrong. (Pressure is left out: pressure on Riverside's ball is
# applied by Harbour, so either team's name can be right.)
OWNED = {"control": "control", "xg": "xG", "threat": "threat", "momentum": "momentum"}
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


def on_pitch(analysis: Analysis) -> list[float]:
    """Players per team: 11 - red cards."""
    ctx = analysis.task.context
    return [float(11 - ctx.sent_off.get(t, 0)) for t in (ctx.home, ctx.away)]


SHIRT = re.compile(r"\b(?:number|no\.?|#)\s*(\d{1,2})\b", re.IGNORECASE)
LAST_MAN = re.compile(r"\blast[\s-]man\b", re.IGNORECASE)


def allowed_numbers(analysis: Analysis) -> list[float]:
    ctx = analysis.task.context
    moment = analysis.task.moment
    # With a team sheet, shirt numbers are checked where they are said
    # ("number 5"), not allowed anywhere; without one, any shirt on the pitch.
    shirts = (
        []
        if ctx.lineup
        else [
            float(pid.rsplit("-", 1)[-1])
            for pid in ctx.players
            if pid.rsplit("-", 1)[-1].isdigit()
        ]
    )
    return [
        *analysis.values.values(),
        *ctx.score,
        float(ctx.minute),
        float(moment.clock.minute),
        *shirts,
        *on_pitch(analysis),
        *map(float, analysis.task.counts.values()),
        # Numbers in code's display strings ("xG 0.45", "Harbour lead 1-0").
        *(x for v in analysis.task.display.values() for x, _, _ in numbers(v)),
    ]


SPELLED = r"(?:nil|zero|one|two|three|four|five|six|seven|eight|nine)"
SPELLED_SCORE = re.compile(rf"\b{SPELLED}\s*(?:-|to|–)\s*{SPELLED}\b", re.IGNORECASE)
XG_AS_GOALS = re.compile(r"\b\d+\.\d+\s+goals?\b", re.IGNORECASE)
WHOLE_WITH_DECIMALS = re.compile(r"(?<![\w.])(\d+)\.0+(?![\d])")
SCORE = r"(\d+)\s*[-–]\s*(\d+)"


def number_style(text: str, analysis: Analysis) -> list[str]:
    """Numbers written the way code writes them: counts whole, scores in
    digits with the right team's goals first, xG as 'xG 0.30'."""
    out = []
    for m in WHOLE_WITH_DECIMALS.finditer(text):
        if not re.search(r"xG\s*$", text[: m.start()]):
            out.append(
                f"counts are whole numbers: write {m.group(1)}, not {m.group(0)}"
            )
    if XG_AS_GOALS.search(text):
        out.append("write xG as 'xG 0.30', never '0.3 goals'")
    if SPELLED_SCORE.search(text):
        out.append(
            "write scores in digits, e.g. "
            + analysis.task.display.get("standing", "Riverside 0-1 Harbour")
        )
    ctx = analysis.task.context
    goals = dict(zip((ctx.home, ctx.away), ctx.score, strict=True))
    for team in (ctx.home, ctx.away):
        name = re.escape(ctx.team_names[team])
        other = ctx.away if team == ctx.home else ctx.home
        # "Harbour 1-0 Riverside": the number next to a team is its goals.
        for m in re.finditer(
            rf"\b{name}\s+{SCORE}\s+{re.escape(ctx.team_names[other])}\b",
            text,
            re.IGNORECASE,
        ):
            if (int(m.group(1)), int(m.group(2))) != (goals[team], goals[other]):
                out.append(f"score the wrong way round: it is {score_line(ctx)}")
        # "Harbour lead 1-0" / "Harbour beat Riverside 2-0": the leader's goals first.
        for m in re.finditer(
            rf"\b{name}(?:{LEADS}|\s+(?:beat|beats|defeated|won|win)\b)[^.!?\d]{{0,30}}?{SCORE}",
            text,
            re.IGNORECASE,
        ):
            a, b = int(m.group(m.lastindex - 1)), int(m.group(m.lastindex))
            if a < b:
                out.append(
                    f"the leader's score goes first: {analysis.task.display.get('standing', score_line(ctx))}"
                )
    return list(dict.fromkeys(out))


CARDINALS = {
    w: n
    for n, w in enumerate(
        [
            "zero",
            "one",
            "two",
            "three",
            "four",
            "five",
            "six",
            "seven",
            "eight",
            "nine",
            "ten",
            "eleven",
            "twelve",
            "thirteen",
            "fourteen",
            "fifteen",
            "sixteen",
            "seventeen",
            "eighteen",
            "nineteen",
            "twenty",
        ]
    )
}
ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5}
MULTIPLES = {"twice": 2, "thrice": 3}  # not "once": "once more" means again
# Football nouns a count can be about -> kind of count.
NOUNS = {
    **dict.fromkeys(["pass", "passes"], "passes"),
    **dict.fromkeys(["man", "men", "player", "players"], "players"),
    **dict.fromkeys(["goal", "goals"], "goals"),
    **dict.fromkeys(
        ["counter", "counters", "counter-attack", "counter-attacks", "break", "breaks"],
        "counters",
    ),
    **dict.fromkeys(["card", "cards"], "cards"),
    **dict.fromkeys(["time", "times"], "times"),
}
COUNT = re.compile(
    # A whole number only: "0.61 goals" is xG, not 61 goals.
    r"(?<![\d.])\b(?P<n>\d+(?![.,]\d)|" + "|".join([*CARDINALS, *ORDINALS]) + r")"
    r"(?:\s+(?P<adj>[a-z][a-z'\-]*))?\s+(?P<noun>" + "|".join(NOUNS) + r")\b",
    re.IGNORECASE,
)
MULTIPLE = re.compile(r"\b(" + "|".join(MULTIPLES) + r")\b", re.IGNORECASE)
# Comparison words -> after/before ratio they claim.
COMPARISONS = [
    (r"\bhalved\b|\bhalving\b|\bcut\s+in\s+half\b|\bdown\s+by\s+half\b", 0.5),
    (r"\bhalves\b(?=\s+(from|to|in|after|since))", 0.5),
    (r"\bdoubled\b|\bdoubles\b|\bdoubling\b", 2.0),
    (r"\btripled\b|\btriples\b|\btrebled\b", 3.0),
    (r"\b(up|rises?|rose|climbs?|grows?|grew)\s+by\s+a\s+third\b", 4 / 3),
    (r"\b(down|falls?|fell|drops?|dropped)\s+by\s+a\s+third\b", 2 / 3),
    (r"\b(up|rises?|rose|climbs?|grows?|grew)\s+by\s+half\b", 1.5),
]
COMPARE_TOLERANCE = 0.10


def counts_of_kind(kind: str, analysis: Analysis) -> set[float]:
    """Code-made counts a 'kind' of count may match."""
    task, ctx = analysis.task, analysis.task.context
    c = task.counts
    repeated = {float(v) for k, v in analysis.values.items() if "counters" in k}
    if "counter_goals" in c:
        repeated.add(float(c["counter_goals"]))
    if kind == "passes":
        return {float(c["passes_in_move"])} if "passes_in_move" in c else set()
    if kind == "players":
        teams = on_pitch(analysis)
        return {*teams, abs(teams[0] - teams[1])} - {0.0}
    if kind == "goals":
        return {float(x) for x in ctx.score} | {float(sum(ctx.score))}
    if kind == "counters":
        return repeated | ({1.0} if "build_up" in task.facts else set())
    if kind == "cards":
        return {float(v) for v in ctx.sent_off.values()} | (
            {1.0} if task.moment.kind == "red_card_impact" else set()
        )
    return repeated  # times


def wrong_counts(text: str, analysis: Analysis) -> list[str]:
    out = []
    for m in COUNT.finditer(text):
        word, noun = m.group("n").lower(), m.group("noun").lower()
        n = float(word) if word.isdigit() else CARDINALS.get(word, ORDINALS.get(word))
        adj = (m.group("adj") or "").lower()
        # "second counter goal" counts counter goals: a noun in between decides.
        kind = NOUNS.get(adj, NOUNS[noun])
        if n not in counts_of_kind(kind, analysis):
            out.append(f"'{m.group(0)}': no code-made count of {kind} is {n:g}")
    for m in MULTIPLE.finditer(text):
        n = MULTIPLES[m.group(1).lower()]
        if n not in counts_of_kind("times", analysis):
            out.append(f"'{m.group(1)}': nothing in the evidence happened {n} times")
    return out


def pairs(values: dict[str, float]) -> list[tuple[str, float, float]]:
    """(metric, before, after) for every metric with both."""
    return [
        (k[: -len("_before")], v, values[k[: -len("_before")] + "_after"])
        for k, v in values.items()
        if k.endswith("_before") and k[: -len("_before")] + "_after" in values
    ]


def wrong_comparisons(text: str, analysis: Analysis) -> list[str]:
    ratios = [after / before for _, before, after in pairs(analysis.values) if before]
    out = []
    for pattern, target in COMPARISONS:
        m = re.search(pattern, text, re.IGNORECASE)
        if m and not any(abs(r / target - 1) <= COMPARE_TOLERANCE for r in ratios):
            out.append(
                f"'{m.group(0)}' does not match any before/after change "
                f"(within {COMPARE_TOLERANCE:.0%})"
            )
    return out


def matches(x: float, decimals: int, percent: bool, v: float) -> bool:
    """x as written (with its rounding) is v, or v as a percentage."""
    tol = 0.5 * 10**-decimals + 1e-9
    candidates = [v, v * 100] if percent or abs(v) <= 1 else [v]
    return any(abs(x - c) <= tol for c in candidates)


def known_names(analysis: Analysis) -> set[str]:
    ctx = analysis.task.context
    words = set()
    sheet = [p.name for p in ctx.lineup]
    for name in [
        *ctx.team_names.values(),
        *ctx.players.values(),
        *sheet,
        ctx.home,
        ctx.away,
    ]:
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
        for team, leads in dict.fromkeys(claims)
        if (leader == team) != leads
    ]


def wrong_owner(text: str, analysis: Analysis) -> list[str]:
    """'Harbour's control' when the moment's numbers are Riverside's."""
    ctx = analysis.task.context
    team = analysis.task.moment.team
    if team not in (ctx.home, ctx.away):
        return []
    other = ctx.away if team == ctx.home else ctx.home
    keys = {k.split("_")[0].lower() for k in analysis.values}
    out = []
    for key, word in OWNED.items():
        if key in keys and re.search(
            rf"\b{re.escape(ctx.team_names[other])}'s\s+(\w+\s+)?{word}\b",
            text,
            re.IGNORECASE,
        ):
            out.append(
                f"the {word} numbers are {ctx.team_names[team]}'s, "
                f"not {ctx.team_names[other]}'s"
            )
    return out


def missing_cause(text: str, analysis: Analysis) -> list[str]:
    """A goal code knows came from a counter behind a full-back must say so."""
    facts = analysis.task.facts
    if "build_up" not in facts:
        return []
    out = []
    if not COUNTER_WORDS.search(text):
        out.append("say it came from a counter (the build_up in facts)")
    side = facts.get("side", "")
    if not re.search(
        rf"\b{side}[\s-]*(back|side|flank|channel|wing)\b", text, re.IGNORECASE
    ):
        out.append(f"name the zone: {facts['exploited_zone']}")
    return out


def words_of(text: str) -> set[str]:
    return {w.lower() for w in WORD.findall(text)}


def copied(text: str, examples: Sequence[str]) -> bool:
    mine = words_of(text)
    for line in examples:
        theirs = words_of(line)
        if mine and len(mine & theirs) / len(mine | theirs) > COPY_LIMIT:
            return True
    return False


LOCKED_NUMBER = re.compile(r"\d+(?:\.\d+)?(?:-\d+)?(?:\s*%)?")
TOKEN = re.compile(r"\[([TSNX]\d+)\]")


def lock(text: str, analysis: Analysis) -> tuple[str, dict[str, str]]:
    """Names, scores, numbers -> typed tokens [T1], [S1], [N1], [X1] for the
    Localizer (the type tells it how the token reads in a sentence)."""
    ctx = analysis.task.context
    names = sorted(
        {*ctx.team_names.values(), *ctx.players.values(), "xG"}, key=len, reverse=True
    )
    pattern = re.compile(
        "|".join([*(rf"\b{re.escape(n)}\b" for n in names), LOCKED_NUMBER.pattern])
    )
    slots: dict[str, str] = {}

    def slot(m):
        s = m.group(0)
        kind = (
            "X"
            if s == "xG"
            else "S"
            if re.fullmatch(r"\d+-\d+", s)
            else "N"
            if s[0].isdigit()
            else "T"
        )
        key = f"[{kind}{sum(k[1] == kind for k in slots) + 1}]"
        slots[key] = s
        return key

    return pattern.sub(slot, text), slots


def unlock(reply: str, slots: dict[str, str]) -> tuple[str | None, str | None]:
    """(translation, None) or (None, why): every token once, no other digits."""
    found = TOKEN.findall(reply)
    if sorted(found) != sorted(k.strip("[]") for k in slots):
        return None, "copy every token ([T1], [S1], [N1] ...) exactly once, unchanged"
    if re.search(r"\d", TOKEN.sub("", reply)):
        return None, "write no digits of your own; the numbers are the tokens"
    return TOKEN.sub(lambda m: slots[m.group(0)], reply), None


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


def shirts_said(text: str, analysis: Analysis) -> tuple[str, list[str]]:
    """Text without the shirt numbers that are on the team sheet, and the
    reasons for any that are not."""
    ctx = analysis.task.context
    if not ctx.lineup:
        return text, []
    sheet = {p.shirt_number for p in ctx.lineup}
    bad = [
        f"'{m.group(0)}': no player wears number {m.group(1)}"
        for m in SHIRT.finditer(text)
        if int(m.group(1)) not in sheet
    ]
    return SHIRT.sub(
        lambda m: "" if int(m.group(1)) in sheet else m.group(0), text
    ), bad


def wrong_players(text: str, analysis: Analysis) -> list[str]:
    """Position, style or shirt said with a player's name must match the sheet."""
    ctx = analysis.task.context
    out = []
    claim_words = "|".join(sorted(map(re.escape, CLAIMS), key=len, reverse=True))
    style_words = "|".join(sorted(map(re.escape, STYLE_WORDS), key=len, reverse=True))
    for p in ctx.lineup:
        name = name_pattern(p)
        team = re.escape(ctx.team_names.get(p.team_id, p.team_id))
        joiner = rf",?\s+(?:(?:the|their|his|{team}'s)\s+)?"
        for words, check in ((claim_words, "position"), (style_words, "style")):
            for m in re.finditer(
                rf"\b(?P<w>{words})\s+{name}\b|\b{name}{joiner}(?P<w2>{words})\b",
                text,
                re.IGNORECASE,
            ):
                word = (m.group("w") or m.group("w2")).lower()
                if check == "position" and p.position not in CLAIMS[word]:
                    out.append(f"{p.name} is not a {word} (team sheet: {p.position})")
                if check == "style" and STYLE_OF.get(word, word) != p.style:
                    out.append(
                        f"{p.name} is not a {word} (team sheet: {p.style or 'no style'})"
                    )
        for m in re.finditer(
            rf"\b(?:number|no\.?|#)\s*(\d{{1,2}})\s+{name}\b"
            rf"|\b{name}\s*\((?:number\s*|no\.?\s*|#)?(\d{{1,2}})\)",
            text,
            re.IGNORECASE,
        ):
            n = int(m.group(1) or m.group(2))
            if n != p.shirt_number:
                out.append(f"{p.name} wears number {p.shirt_number}, not {n}")
    return out


def wrong_numbers(text: str, analysis: Analysis) -> list[str]:
    allowed = allowed_numbers(analysis)
    text, out = shirts_said(text, analysis)
    for x, decimals, percent in numbers(text):
        if not any(matches(x, decimals, percent, v) for v in allowed):
            shown = f"{x:g}{'%' if percent else ''}"
            out.append(
                f"number {shown} is not in the values or the match context; "
                f"use only: {', '.join(f'{k}={v:g}' for k, v in analysis.values.items())}"
            )
    return out


MAX_WORDS = 25  # one on-screen line


def verify(
    text: str,
    analysis: Analysis,
    examples: Sequence[str] = (),
    *,
    max_words: int = MAX_WORDS,
    final: bool = False,
) -> Verdict:
    """`examples`: the Narrator's style examples, which a line must not copy.
    `final`: the match is over (full-time recap), so "sealed the win" is a fact,
    not a prediction."""
    if not text.strip():
        return Verdict(passed=False, reasons=["the line is empty"])
    reasons = wrong_numbers(text, analysis)
    if len(text.split()) > max_words:
        reasons.append(f"too long: at most {max_words} words")
    if analysis.task.persona == "casual" and any(d for _, d, _ in numbers(text)):
        reasons.append(
            "casual line: no index numbers or decimals; say it in words "
            "(e.g. 'halved') from the changes given"
        )
    reasons += wrong_counts(text, analysis)
    reasons += wrong_players(text, analysis)
    if LAST_MAN.search(text) and "last-man" not in analysis.task.facts.get(
        "reason", ""
    ):
        reasons.append(
            "'last man' only when the events show a last-man foul (no other "
            "outfield defender goal-side); they do not here"
        )
    reasons += wrong_comparisons(text, analysis)
    for name in unknown_names(text, analysis):
        reasons.append(f"'{name}' is not a team or a player on the team sheet")
    reasons += score_mistakes(text, analysis)
    reasons += number_style(text, analysis)
    if copied(text, examples):
        reasons.append("too close to a style example: write your own line")
    if PREDICTION.search(text):
        reasons.append("no predictions: describe what happened, not what will happen")
    if SOFT_PREDICTION.search(text) and not final:
        reasons.append(
            "no predictions: the match is not over, so nothing is sealed, "
            "secured or over yet"
        )
    reasons += missing_cause(text, analysis)
    reasons += wrong_owner(text, analysis)
    if WEATHER_CAUSE.search(text):
        reasons.append("do not blame a single event on the weather")
    risky = bool(RISKY.search(text))
    return Verdict(
        passed=not reasons, reasons=reasons, risk_tier="high" if risky else "low"
    )
