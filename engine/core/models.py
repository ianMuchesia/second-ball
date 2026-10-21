"""Probability models: pass success, xG, pressure load, fatigue. Coefficients in engine.yaml."""

import math

from engine.core.pitch import goal_angle, goal_distance


def logistic(z):
    return 1.0 / (1.0 + math.exp(-z))


def pressure_load(distance_m):
    """Engine-internal pressure from one opponent, 1 at 0 m to 0 at 5 m.

    Generator mechanics only, not the pressure metric (Phase 2, Ian's spec).
    """
    return max(0.0, 1.0 - distance_m / 5.0)


def pass_success(
    cfg,
    distance_m,
    passer_load,
    receiver_load,
    forwardness,
    lines_broken,
    cross,
    restart,
    strength=0.5,
):
    m = cfg["pass_model"]
    strength_centre = m.get("strength_centre", 0.5)
    z = (
        m["intercept"]
        - m["per_metre"] * distance_m
        - m["long_per_metre"] * max(0.0, distance_m - m["long_from_m"])
        - m["passer_pressure"] * passer_load
        - m["receiver_pressure"] * receiver_load
        - m["forward_angle"] * forwardness
        - m["per_line_broken"] * lines_broken
        - (m["cross"] if cross else 0.0)
        + (m["restart_bonus"] if restart else 0.0)
        + m["per_strength"]
        * (strength - strength_centre)  # better than the league average
    )
    return logistic(z)


def xg(cfg, x, y, header, assist, bonus=0.0):
    m = cfg["xg_model"]
    z = (
        m["intercept"]
        + m["per_metre"] * goal_distance(x, y)
        + m["per_radian_of_goal"] * goal_angle(x, y)
        + (m["header"] if header else 0.0)
        + m["assist"][assist]
        + bonus
    )
    return logistic(z)


def fatigue(cfg, minute, fatigue_rate):
    """1.0 at kick-off, falling with a curve that is steeper in heat."""
    return max(0.3, 1.0 - cfg["fatigue_k"] * fatigue_rate * (min(minute, 95) / 90) ** 2)
