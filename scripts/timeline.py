"""Draw a match's metric timeline CSV (from the interpreter) as a PNG.

uv run python -m scripts.timeline docs/timelines/demo.csv   # -> docs/timelines/demo.png
"""

import csv
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Reference categorical palette (dataviz skill), slots 1 and 2: home, away.
HOME, AWAY = "#2a78d6", "#eb6834"
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"

PANELS = [
    ("possession_time_last_10m", "Possession (time), last 10 min", "share", True),
    ("field_tilt_last_10m", "Field tilt, last 10 min", "share", True),
    ("xg", "xG, cumulative", "xG", False),
    ("ppda_last_15m", "PPDA, last 15 min (higher = pressing less)", "passes", False),
    (
        "possession_changes_per_min_last_10m",
        "Possession changes per minute, last 10 min",
        "per min",
        False,
    ),
]


def load(path: Path):
    series = defaultdict(lambda: defaultdict(list))  # metric -> owner -> [(min, v)]
    markers = []
    for r in csv.DictReader(path.open()):
        if r["metric"] in ("goal", "red_card"):
            markers.append((float(r["minute"]), r["metric"], r["owner"], r["clock"]))
        else:
            series[r["metric"]][r["owner"]].append(
                (int(r["minute"]), float(r["value"]))
            )
    return series, markers


def half_time(path: Path):
    rows = [r for r in csv.DictReader(path.open()) if r["period"] == "2"]
    return min(float(r["minute"]) for r in rows) if rows else None


def main(argv=None):
    path = Path((argv or sys.argv[1:])[0])
    series, markers = load(path)
    teams = [o for o in series["xg"]]
    colour = dict(zip(teams, (HOME, AWAY), strict=False))
    ht = half_time(path)

    plt.rcParams.update({"font.size": 9, "axes.edgecolor": MUTED, "text.color": INK})
    fig, axes = plt.subplots(len(PANELS), 1, figsize=(10, 12), sharex=True)
    for ax, (metric, title, unit, half_line) in zip(axes, PANELS, strict=True):
        for owner, points in series[metric].items():
            xs, ys = zip(*points, strict=True)
            c = colour.get(owner, MUTED)
            ax.plot(xs, ys, color=c, lw=2, label=owner.replace("_", " ").title())
            ax.annotate(
                owner.split("_")[0].title() if owner != "match" else "",
                (xs[-1], ys[-1]),
                xytext=(4, 0),
                textcoords="offset points",
                va="center",
                color=INK,
            )
        if half_line:
            ax.axhline(0.5, color=MUTED, lw=0.8, ls=":")
        for minute, kind, owner, clock in markers:
            ls = "-" if kind == "goal" else "--"
            ax.axvline(minute, color=colour.get(owner, MUTED), lw=1, ls=ls, alpha=0.8)
        if ht is not None:
            ax.axvline(ht, color=MUTED, lw=0.8)
        ax.set_title(title, loc="left", color=INK)
        ax.set_ylabel(unit, color=MUTED)
        ax.grid(axis="y", color=GRID, lw=0.6)
        ax.spines[["top", "right"]].set_visible(False)

    top = axes[0]
    for minute, kind, owner, clock in markers:
        label = ("Goal " if kind == "goal" else "Red card ") + owner.split("_")[
            0
        ].title()
        top.annotate(
            f"{label} {clock}",
            (minute, 1.0),
            xycoords=("data", "axes fraction"),
            rotation=90,
            va="top",
            ha="right",
            fontsize=8,
            color=MUTED,
        )
    if ht is not None:
        top.annotate(
            "half-time", (ht, 0.02), xycoords=("data", "axes fraction"), color=MUTED
        )
    handles, labels = axes[2].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper right", frameon=False)
    axes[-1].set_xlabel("match minutes played (both halves, stoppage time included)")
    fig.suptitle(
        f"{path.stem}: minute-by-minute metrics (solid line = goal, dashed = red card)",
        x=0.01,
        ha="left",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    out = path.with_suffix(".png")
    fig.savefig(out, dpi=120)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
