"""Nothing spends real requests by accident.

Every command that can call a model takes --provider (default: the free fake
model) and --yes. Before a real run it prints the model, a request estimate
from a free fake-model dry run, and the budget, then asks.
"""

import argparse
import sys
from collections.abc import Callable

from agents.llm.client import LLMClient
from agents.llm.fake import FAKE_MODEL

PROVIDERS = ["fake", "gemini", "foundry"]


def add_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--provider",
        choices=PROVIDERS,
        default="fake",
        help="the model to call; real ones (gemini, foundry) ask first",
    )
    p.add_argument("--yes", action="store_true", help="skip the confirmation")


def dry_run_requests(job: Callable[[LLMClient], object]) -> int:
    """How many model requests a job makes, run once on the free fake model."""
    from agents.live.record import fake_llm

    llm = fake_llm()
    job(llm)
    return len(llm.budget.ledger)


def match_requests(match_file, languages=None, player_recaps="template") -> int:
    """Requests one match makes through the pipeline (a free dry run)."""
    import tempfile
    from pathlib import Path

    from agents.live.record import record

    with tempfile.TemporaryDirectory() as tmp:
        return dry_run_requests(
            lambda f: record(
                Path(match_file), Path(tmp) / "dry", f, languages, player_recaps
            )
        )


def confirm(
    llm: LLMClient,
    estimate: str,
    yes: bool = False,
    ask: Callable[[str], str] = input,
    out: Callable[[str], None] = print,
    interactive: bool | None = None,
) -> None:
    """Before a real run: the model, the estimate and the budget, then a
    question. The fake model is free: no question."""
    if llm.provider.model == FAKE_MODEL:
        return
    out(
        f"Real model: {llm.provider.name} ({llm.provider.model}). {estimate}. "
        f"Budget cap: ${llm.budget.usd_limit:g}."
    )
    if yes:
        return
    if not (sys.stdin.isatty() if interactive is None else interactive):
        raise SystemExit("No terminal to confirm a real run: pass --yes.")
    if ask("Spend these requests? [y/N] ").strip().lower() not in ("y", "yes"):
        raise SystemExit("Cancelled: no requests spent.")
