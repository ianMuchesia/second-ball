"""A player's body (kinematics) and his time to reach the ball.

Movement: accelerate towards a target, arrive (slow down in time to stop on
it), capped by top speed, acceleration and deceleration; he turns at a
limited rate. Reach: from where he is and how he is moving, how long until
he can play a ball at a point (reaction + turning + running).
"""

import math
from dataclasses import dataclass

from engine.core.pitch import LENGTH, WIDTH, clamp


@dataclass
class Player:
    key: tuple  # (side, index): side 0 home, 1 away
    player_id: str
    team_id: str
    keeper: bool
    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0
    facing: float = 0.0  # degrees, 0 = +x, anticlockwise
    react_at: float = 0.0  # he cannot respond to a new ball before this time

    @property
    def pos(self):
        return (self.x, self.y)

    @property
    def speed(self):
        return math.hypot(self.vx, self.vy)

    def move(self, target, cap, dt, p, arrive_in=None):
        """One step towards `target` at no more than `cap` m/s. `arrive_in`:
        a chase, timed to be at the point in that many seconds (with the
        ball), not to stop on it early and not to run past it."""
        dx, dy = target[0] - self.x, target[1] - self.y
        d = math.hypot(dx, dy)
        want = 0.0 if d < 0.1 else min(cap, math.sqrt(2 * p["decel"] * d) * 0.9)
        if arrive_in is not None and d >= 0.1:
            want = min(cap, d / max(arrive_in - p["early_s"], dt))
        wx, wy = (dx / d * want, dy / d * want) if d >= 0.1 else (0.0, 0.0)
        ax, ay = (wx - self.vx) / dt, (wy - self.vy) / dt
        s = self.speed
        if s > 0.5:
            # Along his run: speeding up (accel) or slowing (decel); across
            # it: turning, which has its own (larger) limit.
            tx, ty = self.vx / s, self.vy / s
            along = ax * tx + ay * ty
            nx, ny = ax - along * tx, ay - along * ty
            along = clamp(along, -p["decel"], p["accel"])
            n = math.hypot(nx, ny)
            if n > p["lateral"]:
                nx, ny = nx * p["lateral"] / n, ny * p["lateral"] / n
            ax, ay = along * tx + nx, along * ty + ny
        else:
            a = math.hypot(ax, ay)
            limit = p["accel"] if want > s else p["decel"]
            if a > limit:
                ax, ay = ax * limit / a, ay * limit / a
        self.vx += ax * dt
        self.vy += ay * dt
        s = self.speed
        if s > p["top_speed"]:
            self.vx, self.vy = (
                self.vx * p["top_speed"] / s,
                self.vy * p["top_speed"] / s,
            )
        self.x = clamp(self.x + self.vx * dt, 0.0, LENGTH)
        self.y = clamp(self.y + self.vy * dt, 0.0, WIDTH)

    def face(self, toward, dt, p):
        """Turn (at a limited rate) to face where he runs, or `toward` when slow."""
        if self.speed >= 1.0:
            want = math.degrees(math.atan2(self.vy, self.vx))
        else:
            want = math.degrees(math.atan2(toward[1] - self.y, toward[0] - self.x))
        turn = (want - self.facing + 540.0) % 360.0 - 180.0
        step = p["turn_deg_s"] * dt
        self.facing = (self.facing + clamp(turn, -step, step)) % 360.0


def run_time(d, v0, top, accel):
    """Seconds to cover `d` metres from speed `v0`, accelerating to `top`."""
    if d <= 0.0:
        return 0.0
    t_acc = max(0.0, (top - v0) / accel)
    d_acc = v0 * t_acc + 0.5 * accel * t_acc**2
    if d <= d_acc:
        return (-v0 + math.sqrt(v0 * v0 + 2.0 * accel * d)) / accel
    return t_acc + (d - d_acc) / top


def reach_time(pl, point, now, reach, p):
    """Seconds from `now` until `pl` can play a ball at `point` (within
    `reach` metres of it): his reaction left, the time to kill speed going
    the wrong way, then the run."""
    dx, dy = point[0] - pl.x, point[1] - pl.y
    d = math.hypot(dx, dy)
    wait = max(0.0, pl.react_at - now)
    if d <= reach:
        return wait
    ux, uy = dx / d, dy / d
    along = pl.vx * ux + pl.vy * uy
    across = abs(-pl.vx * uy + pl.vy * ux)
    turn = (max(0.0, -along) + 0.5 * across) / p["decel"]
    return (
        wait + turn + run_time(d - reach, max(0.0, along), p["top_speed"], p["accel"])
    )


def intercept(pl, path, now, reach, height, p):
    """(seconds ahead, point): the first point on the ball's predicted `path`
    he can be at no later than the ball, with it low enough to play. If he
    can be first nowhere, where it stops and when he gets there."""
    for tau, x, y, h in path:
        if h <= height and reach_time(pl, (x, y), now, reach, p) <= tau:
            return tau, (x, y)
    tau, x, y, _ = path[-1]
    return max(tau, reach_time(pl, (x, y), now, reach, p)), (x, y)
