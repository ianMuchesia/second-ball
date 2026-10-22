"""Write docs/metrics/REGISTRY.md from the metric registry (the one source).

uv run python -m scripts.export_metrics_doc
A unit test fails when the file is out of date.
"""

from pathlib import Path

from core.metrics import METRICS

OUT = Path(__file__).resolve().parent.parent / "docs" / "metrics" / "REGISTRY.md"
GROUPS = {"event": "Per event", "team": "Per team", "match": "Per match"}


def windows(m) -> str:
    return ", ".join("whole match" if w is None else f"last {w} min" for w in m.windows)


def render() -> str:
    lines = [
        "# Metric registry",
        "",
        (
            "Generated from `core/metrics/registry.py` by "
            "`uv run python -m scripts.export_metrics_doc`. Do not edit by hand."
        ),
        "",
        "Every number carries `evidence_event_ids`; rates also carry `numerator`",
        "and `denominator`. Thresholds: `core/metrics/config.yaml` (TUNABLE, owner: Ian).",
        "Frame: SPADL (the acting team attacks towards x = 105).",
        "",
    ]
    for grain, title in GROUPS.items():
        ms = [m for m in METRICS.values() if m.grain == grain]
        lines += [
            f"## {title}",
            "",
            "| Metric | Analyst | Casual fan | Unit | Windows | Definition | Formula |",
            "|---|---|---|---|---|---|---|",
        ]
        for m in ms:
            casual = m.display_name.get("casual", "(analyst only)")
            shown = "latest event" if grain == "event" else windows(m)
            lines.append(
                f"| `{m.name}` | {m.display_name['analyst']} | {casual} | {m.unit} | "
                f"{shown} | {m.definition} | `{m.formula}` |"
            )
        lines.append("")
    return "\n".join(lines)


def main():
    OUT.write_text(render())
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
