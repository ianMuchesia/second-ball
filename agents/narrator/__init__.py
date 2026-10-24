"""Narrator voice: few-shot examples Ian writes (examples.yaml)."""

from pathlib import Path

import yaml

EXAMPLES = Path(__file__).resolve().parent / "examples.yaml"

# (match_id, kind, minute): the moment being narrated.
Holdout = tuple[str, str, int]


def examples(persona: str, holdout: Holdout | None = None) -> list[str]:
    """Ian's lines for a persona; placeholders are skipped until he writes them.

    With `holdout`, leave one out: the line written for that same moment is
    left out (the answer must not be in the question)."""
    data = yaml.safe_load(EXAMPLES.read_text())
    return [
        r[persona]
        for r in data["examples"]
        if not r[persona].startswith("PLACEHOLDER")
        and (data.get("match"), r["kind"], r["minute"]) != holdout
    ]
