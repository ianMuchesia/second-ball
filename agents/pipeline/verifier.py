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

import difflib
import gzip
import re
from collections.abc import Sequence
from functools import cache
from pathlib import Path

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
        r"(it|(the|a)\s+(\d+-\d+\s+)?(win|game|match|points|victory|result|\d+-\d+))\b"
    ),
    (
        r"\b(secure|secures|secured|securing)\s+"
        r"(it|(the|a)\s+(\d+-\d+\s+)?(win|game|match|points|victory|result|\d+-\d+))\b"
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
COPY_LIMIT = 0.6  # share of a line's word 3-grams found in one example = a copy
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


RISE = r"ris\w*|rais\w*|up|increas\w*|climb\w*|grow\w*|grew|lift\w*|boost\w*|jump\w*|doubl\w*"
FALL = r"drop\w*|fall\w*|fell|down|decreas\w*|slip\w*|sink\w*|sank|dip\w*|lower\w*|cut\w*|halv\w*"
FROM_TO = re.compile(
    rf"\b(?:({RISE})|({FALL}))\b(?:\W+\w+){{0,5}}?\W+from\s+(?:xG\s+)?(\d+(?:\.\d+)?)\s*"
    rf"(?:%|m)?\s+to\s+(?:xG\s+)?(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)


def wrong_direction(text: str) -> list[str]:
    """'drop from 0.71 to 0.80' says down while the numbers go up (and the
    reverse): the word must agree with the numbers."""
    out = []
    for m in FROM_TO.finditer(text):
        rise, fall, a, b = m.groups()
        a, b = float(a), float(b)
        if (fall and b > a) or (rise and b < a):
            word = (fall or rise).lower()
            out.append(
                f"'{word}' but the number goes from {a:g} to {b:g}: "
                f"say it {'rose' if b > a else 'fell'}"
            )
    return out


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
    task = analysis.task
    c = task.counts
    # Counts named for this kind ("passes_completed" for passes): a player's.
    named = {float(v) for k, v in c.items() if kind.rstrip("s") in k}
    return named | counts_by_kind(kind, analysis)


def counts_by_kind(kind: str, analysis: Analysis) -> set[float]:
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


COUNTED = re.compile(
    r"\b(?P<n>\d+|" + "|".join([*CARDINALS, *ORDINALS]) + r")\b"
    r"(?:\s+(?!\d)[\w'\-]+){0,2}?\s+(?P<noun>goal|pass|shot|chance)(?:e?s)?\b",
    re.IGNORECASE,
)


def as_number(word: str) -> float | None:
    word = word.lower()
    if word.isdigit():
        return float(word)
    n = CARDINALS.get(word, ORDINALS.get(word))
    return None if n is None else float(n)


def unphrased_counts(text: str, analysis: Analysis) -> list[str]:
    """A count code phrased ("Harbour's second goal on the counter") must be
    said as that phrase: "a counter creates 2 counter goals" attaches the
    right number to the wrong thing."""
    out = []
    for phrase in analysis.task.display.values():
        m = COUNTED.search(phrase)
        if m is None or phrase.lower() in text.lower():
            continue
        n, noun = as_number(m.group("n")), m.group("noun").lower()
        if n is None or n < 2:
            continue  # "one pass" is ordinary English; the error is 2+ misattached
        # Whose count: the team before it, a digit or a word ("Riverside's
        # 27 shots", "Harbour's second goal on the counter").
        owner = re.match(r"(.+?)'s\s+$", phrase[: m.start()])
        for said in COUNTED.finditer(text):
            if as_number(said.group("n")) != n or said.group("noun").lower() != noun:
                continue
            before = team_before(text, said.start(), analysis)
            if owner and owner.group(1) in (
                before,
                subject(text, said.start(), analysis),
                # "Despite 35 shots, Riverside...": the team comes after.
                None if before else team_after(text, said.end(), analysis),
            ):
                continue  # "Riverside ... 27 shots": the right team's count
            out.append(f"say this count as given: '{phrase}'")
            break
    return list(dict.fromkeys(out))


SCORES = re.compile(rf"\b\d+\s*[-–]\s*\d+\b|{SPELLED_SCORE.pattern}", re.IGNORECASE)


def score_repeated(text: str) -> list[str]:
    """Style: the score at most once per line."""
    n = len(SCORES.findall(text))
    return [f"give the score once (it appears {n} times)"] if n > 1 else []


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
    """Capitalised words that are not a team, a player or a common word. A
    sentence's first word is capitalised anyway ("Patient passing",
    "Meanwhile"): an English word there is ordinary, unless it looks like a
    name (close to a real one, "Kestrel" for Kestrelle, or capitalised
    elsewhere too). "Okafor makes it happen" still blocks: not English."""
    known = known_names(analysis)
    out = []
    sentences = re.split(r"(?<=[.!?:;])\s+|\n", text)
    later = {
        re.sub(r"'s?$", "", m.group(0))
        for sentence in sentences
        for k, m in enumerate(WORD.finditer(sentence))
        if k > 0
    }
    for sentence in sentences:
        for k, m in enumerate(WORD.finditer(sentence)):
            w = re.sub(r"'s?$", "", m.group(0))  # Riverside's -> Riverside
            if not w[0].isupper() or w.isupper():
                continue  # lower case, or an acronym (xG, PPDA)
            if w.lower() in known or w.lower() in COMMON:
                continue
            if (
                k == 0
                and w.lower() in english()
                and w not in later
                and not close_to_a_name(w, known)
            ):
                continue  # an ordinary English word starting the sentence
            out.append(w)
    return out


@cache
def english() -> frozenset[str]:
    """Lowercase English words (SCOWL, agents/pipeline/words/README.md)."""
    path = Path(__file__).with_name("words") / "english.txt.gz"
    with gzip.open(path, "rt") as f:
        return frozenset(f.read().split())


def close_to_a_name(word: str, known: set[str]) -> bool:
    return bool(difflib.get_close_matches(word.lower(), known, n=1, cutoff=0.75))


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
        for verb, leads in (("leading", True), ("trailing", False)):
            for m in re.finditer(rf"\b{verb}\s+{name}\b", text, re.IGNORECASE):
                who = participle_team(text, m, team, other, analysis)
                if who is not None:
                    claims.append((who, leads))
    score = f"{ctx.team_names[ctx.home]} {home}-{away} {ctx.team_names[ctx.away]}"
    return [
        f"wrong about the score: it is {score}, so {ctx.team_names[team]} "
        f"{'do not lead' if leads else 'are not behind'}"
        for team, leads in dict.fromkeys(claims)
        if (leader == team) != leads
    ]


def participle_team(text, m, named, other, analysis):
    """Who 'trailing X' / 'leading X' (match `m`) says is behind or ahead.
    "Trailing Riverside build..." (X described): X. "Harbour, trailing
    Riverside" or "while trailing Harbour by a goal" (the verb, X its
    object): the team doing it, the one named before or the clause's
    subject. "trailing Riverside 0-1 Harbour" quotes the score: no claim of
    its own (the score is checked as a score). None when it cannot tell."""
    ctx = analysis.task.context
    team_of = {ctx.team_names[t].lower(): t for t in (ctx.home, ctx.away)}
    names = "|".join(re.escape(n) for n in ctx.team_names.values())
    if re.match(rf"\s*{SCORE}\s+(?:{names})\b", text[m.end() :], re.IGNORECASE):
        return None
    before = text[: m.start()]
    doer = re.search(
        rf"\b({names})(?:\s*,|\s+(?:are|is|was|were)(?:\s+still|\s+now)?)?\s*$",
        before,
        re.IGNORECASE,
    )
    if doer:
        return team_of[doer.group(1).lower()]
    verb = re.search(
        r"\b(?:while|when|as|after|despite|since)\s*$", before, re.IGNORECASE
    )
    if verb or re.match(r"\s+by\b", text[m.end() :], re.IGNORECASE):
        said = subject(text, m.start(), analysis)
        if said is None or said.lower() == ctx.team_names[named].lower():
            return None
        return other
    return named


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


def team_before(text: str, at: int, analysis: Analysis) -> str | None:
    """The team named last before position `at`, in the same sentence; a
    team named as a place ("behind Riverside's left-back") does not count."""
    start = max(text.rfind(c, 0, at) for c in ".!?;:") + 1
    seg = text[start:at]
    names = "|".join(re.escape(n) for n in analysis.task.context.team_names.values())
    found = [
        m.group(1)
        for m in re.finditer(rf"\b({names})\b", seg)
        if not PLACE.search(seg[: m.start()])
    ]
    return found[-1] if found else None


def team_after(text: str, at: int, analysis: Analysis) -> str | None:
    """The team named first after position `at`, in the same sentence; not
    one named as a place."""
    ends = [i for i in (text.find(c, at) for c in ".!?;") if i >= 0]
    seg = text[at : min(ends, default=len(text))]
    names = "|".join(re.escape(n) for n in analysis.task.context.team_names.values())
    found = (
        m.group(1)
        for m in re.finditer(rf"\b({names})\b", seg)
        if not PLACE.search(seg[: m.start()])
    )
    return next(found, None)


def owner_of(key: str, analysis: Analysis) -> str | None:
    return analysis.owners.get(key) or (
        None if analysis.owners else analysis.task.moment.team
    )


def sentence_start(text: str, at: int) -> int:
    return max(text.rfind(c, 0, at) for c in ".!?;:") + 1


def subject(text: str, at: int, analysis: Analysis) -> str | None:
    """The team a sentence (or clause after ':') starts with: its subject."""
    seg = text[sentence_start(text, at) : at].lstrip()
    return next(
        (n for n in analysis.task.context.team_names.values() if seg.startswith(n)),
        None,
    )


def credited(text: str, at: int, word: str, analysis: Analysis) -> str | None:
    """Whose `word` (control, xG) the number at `at` is said to be: a
    possessive on it ("Harbour's control index ... 0.8"), else the sentence's
    subject ("Harbour sealed it as control rose to 0.8"). A team named only
    as an object ("behind Riverside's left-back") credits nothing."""
    seg = text[sentence_start(text, at) : at]
    if word.lower() not in seg.lower():
        return None
    names = "|".join(re.escape(n) for n in analysis.task.context.team_names.values())
    owned = list(
        re.finditer(
            rf"\b({names})'s\s+(?:[\w-]+\s+){{0,2}}?{re.escape(word)}\b",
            seg,
            re.IGNORECASE,
        )
    )
    if owned:
        return owned[-1].group(1)
    return clause_team(text, at, analysis)


# A team named after these is a place on the pitch or an object, not the
# one whose number it is: "behind Riverside's left-back", "against Harbour",
# "trailing Harbour" (the team trailed, not the one acting).
PLACE = re.compile(
    r"\b(?:behind|against|past|beyond|around|through|into|inside|outside|"
    r"at|on|over|than|from|beat|beats|defeated|defeat|beating|leading|trailing)\s+(?:the\s+)?$",
    re.IGNORECASE,
)


def clause_team(text: str, at: int, analysis: Analysis) -> str | None:
    """The team acting in the clause the number at `at` is in: the last
    team named before it in its sentence, leaving out a team named as a
    place or an object ("Harbour lead as Riverside create a chance worth
    xG 0.34": Riverside's xG)."""
    seg = text[sentence_start(text, at) : at]
    names = "|".join(re.escape(n) for n in analysis.task.context.team_names.values())
    found = [
        m.group(1)
        for m in re.finditer(rf"\b({names})\b", seg)
        if not PLACE.search(seg[: m.start()])
    ]
    return found[-1] if found else subject(text, at, analysis)


def wrong_owners(text: str, analysis: Analysis) -> list[str]:
    """A team's number credited to the other team, in any sentence, also as
    an implied subject: "Harbour sealed it as control rose to 0.8" when the
    control is Riverside's."""
    ctx = analysis.task.context
    out = []
    for m in NUMBER.finditer(text):
        raw = m.group(1)
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        x, percent = float(raw), bool(m.group(2))
        for key, v in analysis.values.items():
            word = next((w for k, w in OWNED.items() if k in key.lower()), None)
            team = owner_of(key, analysis)
            if not word or team is None or not matches(x, decimals, percent, v):
                continue
            said = credited(text, m.start(), word, analysis)
            if said is not None and said != ctx.team_names[team]:
                out.append(
                    f"the {word} {raw} is {ctx.team_names[team]}'s, not {said}'s"
                )
    return list(dict.fromkeys(out))


CONVERTED = re.compile(
    r"\b(?:convert\w*|capitali[sz]\w*\s+on|tak(?:e|es|ing)|put\s+away|scor\w*\s+from)\s+"
    r"(?:all\s+|just\s+|only\s+)?(?P<n>\d+|"
    + "|".join(CARDINALS)
    + r")\s+(?:\w+\s+)?chances?\b",
    re.IGNORECASE,
)


def chances_as_goals(text: str, analysis: Analysis) -> list[str]:
    """'Converted 4 big chances' means 4 goals: the number must be goals scored."""
    goals = {float(x) for x in analysis.task.context.score}
    out = []
    for m in CONVERTED.finditer(text):
        n = as_number(m.group("n"))
        if n is not None and n not in goals:
            out.append(
                f"'{m.group(0)}' says {n:g} chances converted (goals); "
                f"the score is {score_line(analysis.task.context)}"
            )
    return out


def xg_relation(text: str, analysis: Analysis) -> list[str]:
    """xG before a move and the chance's own xG are separate numbers: never
    'from 0.16 to 0.45' or 'turning 0.16 into 0.45'."""
    v = analysis.values
    pairs = [
        (v[k], v[k.replace("xg_before", "shot_xg")])
        for k in v
        if k.endswith("xg_before") and k.replace("xg_before", "shot_xg") in v
    ]
    out = []
    for before, chance in pairs:
        a, b = as_written(before), as_written(chance)
        if re.search(rf"{a}.{{0,30}}?\b(?:to|into)\b.{{0,20}}?{b}", text) or re.search(
            rf"{b}.{{0,15}}?\bfrom\b.{{0,10}}?{a}", text
        ):
            out.append(
                f"xG {before:.2f} before the move and the chance's xG {chance:.2f} "
                "are separate numbers, not one becoming the other"
            )
    return out


def as_written(x: float) -> str:
    """A pattern for x as a line may write it: 0.16, 0.162 or 0.2 (xG optional)."""
    forms = {f"{x:.1f}", f"{x:.2f}", f"{x:.3f}".rstrip("0")}
    return r"(?:xG\s+)?(?:" + "|".join(re.escape(f) for f in sorted(forms)) + r")\b"


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


def trigrams(text: str) -> set[tuple[str, ...]]:
    words = [w.lower() for w in WORD.findall(text)]
    return set(zip(words, words[1:], words[2:], strict=False))


def copied(text: str, examples: Sequence[str]) -> bool:
    """A backstop to leave-one-out: the line shares at least COPY_LIMIT of
    its word 3-grams with an example (single shared words like "Harbour lead"
    are fine; whole phrases are not)."""
    mine = trigrams(text)
    return bool(mine) and any(
        len(mine & trigrams(line)) / len(mine) >= COPY_LIMIT for line in examples
    )


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
    text = SHIRT.sub(lambda m: "" if int(m.group(1)) in sheet else m.group(0), text)
    # "Stonebridge (5)": his own number in brackets is a shirt number too; a
    # wrong one stays (and wrong_players names it).
    for player in ctx.lineup:
        text = re.sub(
            rf"\b({name_pattern(player)})\s*\((?:number\s*|no\.?\s*|#)?"
            rf"{player.shirt_number}\)",
            r"\1",
            text,
            flags=re.IGNORECASE,
        )
    return text, bad


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
LONG_GRACE = 1.5  # up to this x the limit a true line airs (noted, wrapped)


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
    notes = []
    words = len(text.split())
    if words > max_words * LONG_GRACE:
        reasons.append(f"too long: at most {max_words} words")
    elif words > max_words:
        notes.append(f"long: {words} words (limit {max_words}); the screen wraps it")
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
    reasons += wrong_direction(text)
    reasons += unphrased_counts(text, analysis)
    reasons += wrong_owners(text, analysis)
    reasons += chances_as_goals(text, analysis)
    reasons += xg_relation(text, analysis)
    reasons = list(dict.fromkeys(reasons))
    notes += score_repeated(text)  # tone: logged only
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
        passed=not reasons,
        reasons=reasons,
        risk_tier="high" if risky else "low",
        notes=notes,
    )


WORD_GOALS = {"nil": 0, **{w: n for w, n in CARDINALS.items() if n <= 9}}
SPELLED_PAIR = re.compile(
    rf"\b(?P<a>{SPELLED})(?P<sep>\s*(?:-|to|–)\s*)(?P<b>{SPELLED})\b", re.IGNORECASE
)
WON = r"(?:beat|beats|defeated|defeat|defeats|overcame|edged|edge|edges)"


def normalise(text: str, analysis: Analysis) -> tuple[str, list[str]]:
    """The format tier: fixes code makes itself, with no retry, when the
    meaning is clear. A spelled-out score becomes digits in the same order
    ("two-nil" -> "2-0"; the truth rules then check that order), a count's
    decimals go ("13.0 shots" -> "13 shots"), and a win written in fixture
    order ("Harbour defeated Riverside 0-2") is put leader first ("2-0").
    "Harbour lead Riverside 0-1" is not fixed: it says Harbour lead with 0."""
    fixes = []

    def digits(m):
        out = f"{WORD_GOALS[m.group('a').lower()]}-{WORD_GOALS[m.group('b').lower()]}"
        fixes.append(f"'{m.group(0)}' -> '{out}'")
        return out

    text = SPELLED_PAIR.sub(digits, text)

    def whole(m):
        if re.search(r"xG\s*$", text[: m.start()]):
            return m.group(0)
        fixes.append(f"'{m.group(0)}' -> '{m.group(1)}'")
        return m.group(1)

    text = WHOLE_WITH_DECIMALS.sub(whole, text)
    ctx = analysis.task.context
    goals = dict(zip((ctx.home, ctx.away), ctx.score, strict=True))
    for team in (ctx.home, ctx.away):
        other = ctx.away if team == ctx.home else ctx.home
        if goals[team] <= goals[other]:
            continue  # only the winner "beat" anyone
        w, lose = (re.escape(ctx.team_names[x]) for x in (team, other))
        pattern = rf"\b({w}\s+{WON}\s+{lose}\s+){SCORE}"

        def leader_first(m, won=goals[team], lost=goals[other]):
            a, b = int(m.group(2)), int(m.group(3))
            if (a, b) == (lost, won) and a < b:  # fixture order
                fixes.append(f"'{a}-{b}' -> '{b}-{a}' (leader first)")
                return f"{m.group(1)}{b}-{a}"
            return m.group(0)

        text = re.sub(pattern, leader_first, text, flags=re.IGNORECASE)
    return text, fixes


def check(
    text: str,
    analysis: Analysis,
    examples: Sequence[str] = (),
    *,
    max_words: int = MAX_WORDS,
    final: bool = False,
) -> Verdict:
    """How the pipeline checks a draft, tier by tier: format fixes in code
    (no retry), then the truth rules (block and retry); tone is only noted.
    The verdict's `text` is what would air."""
    fixed, fixes = normalise(text, analysis)
    return verify(
        fixed, analysis, examples, max_words=max_words, final=final
    ).model_copy(update={"text": fixed, "fixes": fixes})
