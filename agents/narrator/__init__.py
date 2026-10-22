"""Narrator voice: few-shot examples Ian writes (examples.yaml)."""

from pathlib import Path

import yaml

EXAMPLES = Path(__file__).resolve().parent / "examples.yaml"


def examples(persona: str) -> list[str]:
    """Ian's lines for a persona; placeholders are skipped until he writes them."""
    rows = yaml.safe_load(EXAMPLES.read_text())["examples"]
    return [r[persona] for r in rows if not r[persona].startswith("PLACEHOLDER")]
