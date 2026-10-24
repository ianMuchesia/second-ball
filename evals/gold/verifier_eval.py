"""How accurate is the Verifier itself? Every draft it caught in real runs,
labelled by Ian, run through the current Verifier.

    uv run python -m evals.gold.verifier_eval        # -> docs/EVAL.md "verifier"

A draft should be blocked if Ian labelled it a real mistake (or the Verifier
blocked it for the wrong reason, or he found an error it missed); it should
pass if he labelled it a false alarm or style only (its format is fixed in
code). Each draft is checked as the pipeline checks a line: format fixes in
code first, then the truth rules (agents.pipeline.verifier.check).

The moment each draft was about is rebuilt from the demo match; recaps see
the lines that aired before the whistle (their values come from the same
moments, so a free fake-model recording gives them).
"""

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path

from agents.live.record import fake_llm, record
from agents.mcp_server.data import MatchData
from agents.pipeline.facts import context_at, task_for
from agents.pipeline.models import Analysis, NarrationTask
from agents.pipeline.recap import MAX_WORDS as RECAP_WORDS
from agents.pipeline.recap import Aired, recap_task
from agents.pipeline.verifier import MAX_WORDS, check
from agents.pipeline.workflow import values_of
from core.contracts import Insight, Moment, Overlay
from core.metrics import Events
from evals.gold.caught import kind_of
from evals.sections import write_section

ROOT = Path(__file__).resolve().parents[2]
CAUGHT = Path(__file__).resolve().parent / "caught"
MATCH = ROOT / "demo" / "match.jsonl"
BLOCK = {"real_mistake", "wrong_reason"}
# The same 18 drafts through the Verifier before the tiers (24 Oct 2026).
BEFORE = """**Before the tiers (24 Oct, same 18 drafts):** 18 blocked, 6 of them false
alarms (precision 67%); 12 real errors, but 5 blocked only for a style reason
while the real error went unnamed (chances counted as goals, a recap's wrong
owner). **After:** below. Ian's labels found the misses; each is now a test
(`tests/unit/test_verifier_tiers.py`)."""


@dataclass
class Item:
    row: dict
    analysis: Analysis
    max_words: int
    final: bool

    @property
    def should_block(self) -> bool:
        return self.row["human_label"] in BLOCK or bool(self.row.get("missed"))


def insight(task: NarrationTask) -> Insight:
    return Insight(
        claim="x",
        mechanism="y",
        evidence_event_ids=task.moment.evidence_event_ids,
        confidence=1.0,
    )


def aired_lines(bundle: Path) -> list[tuple[float, Aired]]:
    """(aired_t, line) for every narrative that aired in a fake recording."""
    tasks = {}
    for line in (bundle / "narrations.jsonl").read_text().splitlines():
        n = json.loads(line)
        if n.get("task"):
            tasks[n["overlay_id"]] = NarrationTask.model_validate(n["task"])
    out = []
    for line in (bundle / "overlays.jsonl").read_text().splitlines():
        o = json.loads(line)
        if o["status"] == "aired" and o["overlay_id"] in tasks:
            t = o.pop("aired_t")
            out.append((t, Aired(Overlay.model_validate(o), tasks[o["overlay_id"]])))
    return out


def items(data: MatchData, bundle: Path) -> list[Item]:
    moments = {m.moment_id: m for m in data.moments}
    aired = aired_lines(bundle)
    out = []
    for f in sorted(CAUGHT.glob("*.json")):
        for row in json.loads(f.read_text()):
            kind, persona = row["kind"], row["persona"]
            if not kind.startswith("recap_"):
                m = moments[row["overlay_id"].rsplit("-", 1)[0]]
                task = task_for(data, m, persona, [])
                a = Analysis(task=task, insight=insight(task), values=values_of(task))
                out.append(Item(row, a, MAX_WORDS, final=False))
                continue
            when = kind.removeprefix("recap_")
            items_ = data.events.items
            upto = [e for e in items_ if when == "full_time" or e.period == 1]
            events = Events.for_match(data.match, upto)
            last = upto[-1]
            ctx = context_at(
                MatchData(data.match, upto),
                Moment(
                    moment_id=f"{data.match.match_id}-{when}",
                    kind=when,
                    team=None,
                    clock=last.model_dump(include={"period", "minute", "second"}),
                    importance=1.0,
                    metrics_before={},
                    metrics_after={},
                    evidence_event_ids=[last.event_id],
                ),
            )
            whistle = events.elapsed[-1]
            mine = [a for t, a in aired if t <= whistle and a.task.persona == persona]
            task, values, owners = recap_task(when, events, ctx, mine, persona, [])
            a = Analysis(task=task, insight=insight(task), values=values, owners=owners)
            out.append(Item(row, a, RECAP_WORDS, final=when == "full_time"))
    return out


def run() -> tuple[list[tuple[Item, object]], str]:
    data = MatchData.from_file(MATCH)
    with tempfile.TemporaryDirectory() as tmp:
        bundle = record(MATCH, Path(tmp) / "fake", fake_llm())
        checked = [
            (i, check(i.row["text"], i.analysis, max_words=i.max_words, final=i.final))
            for i in items(data, bundle)
        ]
    return checked, render(checked)


def right_reason(item: Item, verdict) -> bool:
    """Blocked for the error Ian found: a missed error must now be named."""
    missed = set(item.row.get("missed") or [])
    if verdict.passed:
        return False
    if not missed:
        return item.row["human_label"] in BLOCK
    return bool(missed & {kind_of(r) for r in verdict.reasons})


def render(checked) -> str:
    blocks = [(i, v) for i, v in checked if not v.passed]
    should = [i for i, _ in checked if i.should_block]
    caught = [i for i, v in checked if right_reason(i, v)]
    false_alarms = [i for i, v in blocks if not i.should_block]
    missed = [i for i, v in checked if i.should_block and not right_reason(i, v)]
    lines = [
        "# Verifier accuracy on real caught drafts",
        "",
        BEFORE,
        "",
        f"{len(checked)} drafts the Verifier blocked in real Gemini runs, labelled by",
        "Ian (`evals/gold/caught/`), run through today's Verifier (format fixes in",
        "code, then the truth rules).",
        "",
        (
            f"- **Blocked:** {len(blocks)}; false alarms (Ian: the line was "
            f"fine): {len(false_alarms)}."
        ),
        (
            f"- **Real errors:** {len(should)}; blocked for the right reason "
            f"{len(caught)}, not (passed, or blocked for another reason) "
            f"{len(missed)}."
        ),
        "",
        "| # | Minute | Ian's label | Should block | Today | Right reason | Reasons / format fixes |",
        "|---|---|---|---|---|---|---|",
    ]
    for k, (i, v) in enumerate(checked, 1):
        why = "; ".join(v.reasons) if not v.passed else "; ".join(v.fixes) or "-"
        lines.append(
            f"| {k} | {i.row['minute']} | {i.row['human_label']} | "
            f"{'yes' if i.should_block else 'no'} | "
            f"{'blocked' if not v.passed else 'passes'} | "
            f"{'yes' if right_reason(i, v) else ('-' if not i.should_block else 'no')} | "
            f"{why.replace('|', '/')} |"
        )
    return "\n".join(lines)


def main():
    import logging

    logging.disable(logging.WARNING)
    _, body = run()
    write_section(ROOT / "docs" / "EVAL.md", "verifier", body)
    print(body)


if __name__ == "__main__":
    main()
