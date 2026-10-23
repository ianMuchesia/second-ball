"""Narrate a match's big moments through the real pipeline.

Uses the free fake model unless --provider says otherwise (a real one prints
an estimate and asks first), through core/budget.py; MAX_RUN_USD caps it. Prints each line, how many tries it took and why
the Verifier sent lines back, then the cost.

    uv run python -m scripts.narrate_demo --provider gemini
"""

import argparse
import asyncio
from pathlib import Path

from agents.llm import from_env
from agents.llm.guard import add_flags, confirm, dry_run_requests
from agents.mcp_server.data import MatchData
from agents.pipeline.facts import task_for
from agents.pipeline.workflow import narrate


async def run(data: MatchData, llm, min_importance: float, personas: list[str]):
    for moment in data.moments:
        if moment.importance < min_importance:
            continue
        for persona in personas:
            task = task_for(data, moment, persona)
            out = await narrate(llm, task)
            tag = " FALLBACK" if out.fallback else ""
            print(f"\n{moment.clock.minute}' {moment.kind} [{persona}]")
            print(f"  tries {out.attempts}{tag}, risk {out.overlay.risk_tier}")
            for v in out.verdicts:
                if not v.passed:
                    print(f"  sent back: {v.text}\n    why: {'; '.join(v.reasons)}")
            for lang, text in out.overlay.text.items():
                print(f"  {lang}: {text}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--match-file", type=Path, default=Path("demo/match.jsonl"))
    p.add_argument("--min-importance", type=float, default=0.9)
    p.add_argument("--personas", nargs="+", default=["casual", "analyst"])
    add_flags(p)
    args = p.parse_args()
    llm = from_env(provider=args.provider)
    data = MatchData.from_file(args.match_file)
    if args.provider != "fake":
        n = dry_run_requests(
            lambda f: asyncio.run(run(data, f, args.min_importance, args.personas))
        )
        confirm(llm, f"About {n} requests (a free dry run)", args.yes)
    try:
        asyncio.run(run(data, llm, args.min_importance, args.personas))
    finally:
        b = llm.budget
        print(
            f"\nmodel {llm.provider.model}: {len(b.ledger)} calls, "
            f"{b.tokens_spent} tokens, ${b.usd_spent:.4f}"
        )


if __name__ == "__main__":
    main()
