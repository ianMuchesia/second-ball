"""One small real call to each Foundry deployment, through the budget.

    uv run python -m scripts.foundry_smoke            # asks first
    uv run python -m scripts.foundry_smoke --yes

Reads FOUNDRY_* and MAX_RUN_USD from the environment (.env). Each call is
capped at a few hundred tokens (well under a cent); the budget prechecks it
and blocks it before any request if it could pass MAX_RUN_USD. Prints which
deployment each call went to, the model that answered, tokens and cost.
Never prints the endpoint or the key.
"""

import argparse
import sys

from agents.llm import ProviderError, from_env
from agents.llm.base import CALL_ROLE
from core.budget import BudgetExceeded

PROMPT = "Reply with one short sentence: a football commentator's greeting."
MAX_OUTPUT = 300  # gpt-5-mini reasons first; reasoning counts in this cap


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--yes", action="store_true", help="skip the confirmation")
    args = p.parse_args(argv)
    llm = from_env(provider="foundry")
    calls = [
        ("analyst", llm.provider.roles.get("analyst")),
        (None, llm.provider.default),
    ]
    print(
        f"Foundry smoke test: {len(calls)} calls, at most {MAX_OUTPUT} output tokens each."
    )
    print(f"Deployments: {[d for _, d in calls]}. Budget cap: ${llm.budget.usd_limit}.")
    if not args.yes and input("Go? [y/N] ").strip().lower() != "y":
        return 1
    failed = 0
    for role, deployment in calls:
        token = CALL_ROLE.set(role)
        try:
            r = llm.complete(PROMPT, max_output_tokens=MAX_OUTPUT)
            row = llm.budget.ledger[-1]
            print(
                f"OK   {role or 'default':8s} deployment={row['model']} "
                f"answered_by={r.model} tokens={r.input_tokens}+{r.output_tokens} "
                f"usd={row['usd']:.6f} | {r.text.strip()[:100]}"
            )
        except (ProviderError, BudgetExceeded) as e:
            failed += 1
            print(f"FAIL {role or 'default':8s} deployment={deployment}: {e}")
        finally:
            CALL_ROLE.reset(token)
    print(f"Spent ${llm.budget.usd_spent:.6f} of ${llm.budget.usd_limit}.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
