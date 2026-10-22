"""Expected threat (xT): how likely a goal is soon, from where the ball is.

The pitch (each team's own frame, attacking to x = 105) is split into a
16 x 12 grid. From events alone we count, per cell: how often the team shoots
(s), how often a shot there scores (g), how often it moves the ball on (m),
and where successful moves end (T). Value iteration then solves

    xT(z) = s(z) * g(z) + m(z) * sum_z' T(z -> z') * xT(z')

the same fixed point as a value function in reinforcement learning. A
successful pass or carry from z to z' adds xT(z') - xT(z).

Learned from free_simulation events only (scripts/fit_metrics.py); saved as a
versioned artifact in core/metrics/artifacts/.
"""

import json
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from core.contracts import MatchEvent
from core.metrics.events import LENGTH, SHOTS

WIDTH = 68.0
GRID_X, GRID_Y = 16, 12
# Moves the ball on in open play (restarts are left out).
MOVES = {"pass", "cross", "dribble", "take_on"}
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
VERSION = 1


def cell(x: float, y: float) -> tuple[int, int]:
    i = min(int(x / LENGTH * GRID_X), GRID_X - 1)
    j = min(int(y / WIDTH * GRID_Y), GRID_Y - 1)
    return i, j


@dataclass(frozen=True)
class XTGrid:
    values: tuple[tuple[float, ...], ...]  # [i][j], i along x
    version: int
    trained_on: dict

    def at(self, x: float, y: float) -> float:
        i, j = cell(x, y)
        return self.values[i][j]

    def added(self, e: MatchEvent) -> float | None:
        """xT added by a successful move; None for anything else."""
        if e.type not in MOVES or e.outcome != "success":
            return None
        return self.at(e.end_x, e.end_y) - self.at(e.start_x, e.start_y)


def fit(matches: Iterable[Iterable[MatchEvent]], tol=1e-7, max_iter=200):
    """Value iteration on counts from the events. Returns (grid, iterations)."""
    n = GRID_X * GRID_Y
    shots, goals, moves = [0] * n, [0] * n, [0] * n
    moved = [{} for _ in range(n)]  # successful moves: z -> {z': count}

    def idx(x, y):
        i, j = cell(x, y)
        return i * GRID_Y + j

    for events in matches:
        for e in events:
            z = idx(e.start_x, e.start_y)
            if e.type in SHOTS:
                shots[z] += 1
                goals[z] += e.outcome == "success"
            elif e.type in MOVES:
                moves[z] += 1
                if e.outcome == "success":
                    end = idx(e.end_x, e.end_y)
                    moved[z][end] = moved[z].get(end, 0) + 1

    actions = [shots[z] + moves[z] for z in range(n)]
    s = [shots[z] / actions[z] if actions[z] else 0.0 for z in range(n)]
    m = [moves[z] / actions[z] if actions[z] else 0.0 for z in range(n)]
    g = [goals[z] / shots[z] if shots[z] else 0.0 for z in range(n)]
    # T(z -> z') = successful moves z -> z' / all moves from z (failures end it).
    trans = [
        {end: c / moves[z] for end, c in moved[z].items()} if moves[z] else {}
        for z in range(n)
    ]

    xt = [0.0] * n
    for it in range(1, max_iter + 1):
        new = [
            s[z] * g[z] + m[z] * sum(p * xt[e] for e, p in trans[z].items())
            for z in range(n)
        ]
        delta = max(abs(a - b) for a, b in zip(new, xt, strict=True))
        xt = new
        if delta < tol:
            break
    values = tuple(
        tuple(xt[i * GRID_Y + j] for j in range(GRID_Y)) for i in range(GRID_X)
    )
    return values, it


def save(values, trained_on: dict, version: int = VERSION) -> Path:
    ARTIFACTS.mkdir(exist_ok=True)
    path = ARTIFACTS / f"xt_v{version}.json"
    path.write_text(
        json.dumps(
            {
                "version": version,
                "grid": [GRID_X, GRID_Y],
                "frame": "SPADL (each team attacks towards x = 105)",
                "trained_on": trained_on,
                "values": [[round(v, 6) for v in row] for row in values],
            },
            indent=1,
        )
        + "\n"
    )
    return path


@cache
def load(version: int = VERSION) -> XTGrid:
    data = json.loads((ARTIFACTS / f"xt_v{version}.json").read_text())
    return XTGrid(
        values=tuple(tuple(row) for row in data["values"]),
        version=data["version"],
        trained_on=data["trained_on"],
    )
