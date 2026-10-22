"""Draw a match's metric timeline CSV (from the interpreter) as a PNG.

uv run python -m scripts.timeline docs/timelines/demo.csv
    -> docs/timelines/demo.png          the story (control, openness, momentum, ...)
    -> docs/timelines/demo_details.png  every other Phase 2c metric
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
    ("control_index_last_10m", "Control index, last 10 min", "index 0-1", True),
    ("openness_index_last_10m", "Openness index, last 10 min", "index 0-1", False),
    ("momentum", "Momentum (xT, home minus away; above 0 = home on top)", "xT", False),
    ("xg", "xG, cumulative", "xG", False),
    ("ppda_last_15m", "PPDA, last 15 min (higher = pressing less)", "passes", False),
    (
        "possession_changes_per_min_last_10m",
        "Possession changes per minute, last 10 min (scrappiness)",
        "per min",
        False,
    ),
]

DETAILS = [
    ("pressure_on_ball_last_10m", "Pressure on the ball, last 10 min", "0-1"),
    (
        "final_third_pressures_last_10m",
        "Final-third pressures per minute, last 10 min",
        "per min",
    ),
    ("high_turnovers_last_10m", "High turnovers, last 10 min", "count"),
    (
        "counterpress_regains_last_15m",
        "Counter-press regains within 5 s, last 15 min",
        "share",
    ),
    (
        "actions_per_minute_last_10m",
        "Actions per minute in possession, last 10 min",
        "per min",
    ),
    ("seconds_between_actions_last_10m", "Seconds between actions, last 10 min", "s"),
    ("xt_added_total_last_10m", "xT added, last 10 min", "xT"),
    ("big_chances", "Big chances (xG >= 0.3), cumulative", "count"),
    ("pass_accuracy_last_10m", "Pass accuracy, last 10 min", "share"),
    ("pass_difficulty_mean_last_10m", "Average pass difficulty, last 10 min", "0-100"),
    (
        "lines_broken_per_pass_last_10m",
        "Lines broken per completed pass, last 10 min",
        "lines",
    ),
    (
        "defensive_line_gap_last_10m",
        "Back-midfield line gap while defending, last 10 min",
        "m",
    ),
    (
        "overloads_last_10m",
        "Overloads created (danger-weighted), last 10 min",
        "danger",
    ),
    ("bad_situations_last_10m", "Bad situations on the ball, last 10 min", "count"),
    ("upper_hand_last_10m", "Upper hand (0 none, 1, 2 strong), last 10 min", "level"),
    (
        "name_tags",
        "Name-tag moments (100+ km/h shots, 40+ m passes), cumulative",
        "count",
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


def draw(panels, series, markers, colour, ht, title, out, columns=1):
    plt.rcParams.update({"font.size": 9, "axes.edgecolor": MUTED, "text.color": INK})
    rows = -(-len(panels) // columns)
    fig, grid = plt.subplots(
        rows,
        columns,
        figsize=(10 * columns, 2.3 * rows + 0.8),
        sharex=True,
        squeeze=False,
    )
    axes = [ax for col in range(columns) for ax in grid[:, col]]
    for ax, (metric, label, unit, *half) in zip(axes, panels, strict=False):
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
        if half and half[0]:
            ax.axhline(0.5, color=MUTED, lw=0.8, ls=":")
        if metric == "momentum":
            ax.axhline(0, color=MUTED, lw=0.8, ls=":")
        if metric == "openness_index_last_10m":
            # "Usual for this fixture" = openness - openness_vs_expected.
            now = dict(series[metric]["match"])
            vs = series["openness_vs_expected_last_10m"]["match"]
            usual = [(m, now[m] - v) for m, v in vs if m in now]
            if usual:
                ax.axhline(usual[-1][1], color=MUTED, lw=1, ls=":")
                ax.annotate(
                    "usual for this strength gap",
                    (0, usual[-1][1]),
                    xytext=(0, 3),
                    textcoords="offset points",
                    color=MUTED,
                    fontsize=8,
                )
        for minute, kind, owner, _ in markers:
            ls = "-" if kind == "goal" else "--"
            ax.axvline(minute, color=colour.get(owner, MUTED), lw=1, ls=ls, alpha=0.8)
        if ht is not None:
            ax.axvline(ht, color=MUTED, lw=0.8)
        ax.set_title(label, loc="left", color=INK)
        ax.set_ylabel(unit, color=MUTED)
        ax.grid(axis="y", color=GRID, lw=0.6)
        ax.spines[["top", "right"]].set_visible(False)
    for ax in axes[len(panels) :]:
        ax.set_visible(False)

    top = axes[0]
    for minute, kind, owner, clock in markers:
        name = owner.split("_")[0].title()
        top.annotate(
            f"{'Goal' if kind == 'goal' else 'Red card'} {name} {clock}",
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
    handles, labels = next(
        (ax.get_legend_handles_labels() for ax in axes if len(ax.get_lines()) >= 2),
        ([], []),
    )
    fig.legend(handles[:2], labels[:2], loc="upper right", frameon=False)
    for col in range(columns):
        grid[-1, col].set_xlabel(
            "match minutes played (both halves, stoppage included)"
        )
    fig.suptitle(title, x=0.01, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    fig.savefig(out, dpi=110)
    plt.close(fig)
    print(f"wrote {out}")


def main(argv=None):
    path = Path((argv or sys.argv[1:])[0])
    series, markers = load(path)
    teams = [o for o in series["xg"]]
    colour = dict(zip(teams, (HOME, AWAY), strict=False))
    ht = half_time(path)
    note = "(solid line = goal, dashed = red card)"
    draw(
        PANELS,
        series,
        markers,
        colour,
        ht,
        f"{path.stem}: the story, minute by minute {note}",
        path.with_suffix(".png"),
    )
    draw(
        DETAILS,
        series,
        markers,
        colour,
        ht,
        f"{path.stem}: Phase 2c metrics, minute by minute {note}",
        path.with_name(f"{path.stem}_details.png"),
        columns=2,
    )


if __name__ == "__main__":
    main()
