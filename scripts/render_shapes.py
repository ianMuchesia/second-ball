"""Draw every shape of a club as a PNG in docs/shapes/ (check them by eye).

uv run python -m scripts.render_shapes [club_id]   # default: riverside_athletic
"""

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Arc, Circle, Rectangle

from engine.core.pitch import LENGTH, WIDTH
from engine.core.shape import TeamState, anchors
from engine.core.shapes import PHASES, SIDE_Y
from engine.core.sim import load_config
from engine.league import load_league

OUT = Path(__file__).resolve().parent.parent / "docs" / "shapes"
# Where the ball is for each picture (team frame, attacking to the right).
BALL_X = {"in_possession": 60.0, "out_of_possession": 65.0, "transition": 58.0}
LINE = "#f4f7f4"


def draw_pitch(ax):
    ax.add_patch(Rectangle((0, 0), LENGTH, WIDTH, color="#3f7d4a", zorder=0))
    kw = {"fill": False, "color": LINE, "lw": 1.5, "zorder": 1}
    ax.add_patch(Rectangle((0, 0), LENGTH, WIDTH, **kw))
    ax.plot([LENGTH / 2] * 2, [0, WIDTH], color=LINE, lw=1.5, zorder=1)
    ax.add_patch(Circle((LENGTH / 2, WIDTH / 2), 9.15, **kw))
    for x0, sign in ((0, 1), (LENGTH, -1)):
        ax.add_patch(Rectangle((x0, WIDTH / 2 - 20.16), sign * 16.5, 40.32, **kw))
        ax.add_patch(Rectangle((x0, WIDTH / 2 - 9.16), sign * 5.5, 18.32, **kw))
        ax.add_patch(
            Arc(
                (x0 + sign * 11, WIDTH / 2),
                18.3,
                18.3,
                theta1=-53 if sign > 0 else 127,
                theta2=53 if sign > 0 else 233,
                color=LINE,
                lw=1.5,
                zorder=1,
            )
        )
    ax.set_xlim(-3, LENGTH + 3)
    ax.set_ylim(-3, WIDTH + 3)
    ax.set_aspect("equal")
    ax.axis("off")


def render(club_id):
    club = load_league()[club_id]
    cfg = load_config()
    team = TeamState.start(0, club)
    names = {i: (p.role or f"#{p.number}") for i, p in enumerate(club.players)}
    OUT.mkdir(parents=True, exist_ok=True)
    paths = []
    for phase in PHASES:
        for side, y in SIDE_Y.items():
            ball = (BALL_X[phase], y)
            spots = anchors(team, ball, phase, club.block_height, cfg)
            fig, ax = plt.subplots(figsize=(10.5, 7.4), dpi=100)
            draw_pitch(ax)
            for pl, (x, py) in spots.items():
                ax.scatter(
                    x, py, s=420, color="#d64545", edgecolor="white", lw=1.5, zorder=3
                )
                ax.annotate(
                    names[pl],
                    (x, py),
                    color="white",
                    fontsize=8,
                    weight="bold",
                    ha="center",
                    va="center",
                    zorder=4,
                )
            ax.scatter(*ball, s=120, color="white", edgecolor="black", zorder=5)
            ax.annotate(
                "ball",
                ball,
                xytext=(0, -16),
                textcoords="offset points",
                color="white",
                ha="center",
                fontsize=8,
                zorder=5,
            )
            ax.annotate(
                "attacking →", (LENGTH - 2, WIDTH + 1.5), color="black", ha="right"
            )
            title = f"{club.name}: {phase.replace('_', ' ')}, ball {side}"
            ax.set_title(title + "   (left touchline at the top)", fontsize=11)
            path = OUT / f"{club_id}_{phase}_{side}.png"
            fig.savefig(path, bbox_inches="tight", metadata={"Software": None})
            plt.close(fig)
            paths.append(path)
    return paths


if __name__ == "__main__":
    for p in render(sys.argv[1] if len(sys.argv) > 1 else "riverside_athletic"):
        print(p.relative_to(OUT.parent.parent))
