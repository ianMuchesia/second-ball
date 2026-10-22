"""Narrate a match's big moments through the real pipeline.

Uses the model in .env (LLM_PROVIDER, default gemini) through core/budget.py;
MAX_RUN_USD caps the run. Prints each line, how many tries it took and why
the Verifier sent lines back, then the cost.

    MAX_RUN_USD=0.20 uv run python -m scripts.narrate_demo
"""

import argparse
import asyncio
from pathlib import Path

from agents.llm import from_env
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
    args = p.parse_args()
    llm = from_env()
    data = MatchData.from_file(args.match_file)
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
