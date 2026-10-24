"""Every draft the Verifier caught in a real-model run, kept as a gold eval
item: the text, why it was sent back, the moment, and the kind of error.

    uv run python -m evals.gold.caught runs/demo     # -> evals/gold/caught/

Real mistakes from real runs make a better test set than invented ones. The
recorder saves them automatically after every real-model recording.
"""

import argparse
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / "caught"

# The kind of error, from the Verifier's reason (first match wins).
KINDS = [
    ("wrong_direction", ["' but the number goes"]),
    ("wrong_owner", ["'s, not "]),
    (
        "wrong_score",
        [
            "wrong about the score",
            "leader's score",
            "scores in digits",
            "wrong way round",
        ],
    ),
    (
        "wrong_number",
        ["number ", "whole numbers", "xG as", "no index numbers", "halved", "doubled"],
    ),
    # The name check flags any unknown capitalised word: a real invention
    # ("Kestrel" as a player) or a false alarm ("Meanwhile" starting a
    # sentence). human_label says which.
    ("unknown_name", ["is not a team or a player"]),
    ("invented_fact", ["no code-made count", "'last man' only", "shirt"]),
    ("prediction", ["prediction"]),
    ("copied", ["style example"]),
    ("too_long", ["too long"]),
    ("no_answer", ["no answer"]),
]


def kind_of(reason: str) -> str:
    return next((k for k, keys in KINDS if any(x in reason for x in keys)), "other")


def caught(bundle: Path) -> list[dict]:
    meta = json.loads((bundle / "meta.json").read_text())
    minute = {
        o["overlay_id"]: o["t_in"]["match"]["minute"]
        for o in map(json.loads, (bundle / "overlays.jsonl").read_text().splitlines())
    }
    out = []
    for line in (bundle / "narrations.jsonl").read_text().splitlines():
        n = json.loads(line)
        for attempt, v in enumerate(n["verdicts"], 1):
            if v["passed"] or not v["text"]:
                continue  # passed, or no answer at all: not a caught draft
            out.append(
                {
                    "model": meta["model"],
                    "recorded_at": meta["recorded_at"],
                    "match_id": meta["match_id"],
                    "overlay_id": n["overlay_id"],
                    "kind": n["kind"],
                    "minute": minute.get(n["overlay_id"]),
                    "persona": n["persona"],
                    "attempt": attempt,
                    "text": v["text"],
                    "reasons": v["reasons"],
                    "errors": sorted({kind_of(r) for r in v["reasons"]}),
                    # A person's call: was the Verifier right to send it back?
                    "human_label": None,
                }
            )
    return out


def save(bundle: Path, out_dir: Path = OUT) -> Path | None:
    """Writes <match>-<recorded_at>.json (one file per recording); None if
    the run caught nothing or used the fake model."""
    meta = json.loads((bundle / "meta.json").read_text())
    rows = caught(bundle)
    if meta["model"] == "fake-model" or not rows:
        return None
    stamp = meta["recorded_at"][:19].replace(":", "")
    path = out_dir / f"{bundle.name}-{stamp}.json"
    out_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=1, ensure_ascii=False) + "\n")
    return path


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("bundles", nargs="+", type=Path)
    for b in p.parse_args(argv).bundles:
        print(save(b) or f"{b}: nothing caught (or the fake model)")


if __name__ == "__main__":
    main()
